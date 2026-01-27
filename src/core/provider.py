from __future__ import annotations

import abc
import inspect
from typing import TYPE_CHECKING, Any

import grpc  # type: ignore[import-untyped]
import orjson
from tiebameow.utils.logger import logger

from src.core.registry import rule_functions
from src.rpc import review_service_pb2, review_service_pb2_grpc

if TYPE_CHECKING:
    from tiebameow.models.dto import CommentDTO, PostDTO, ThreadDTO

    type ReviewData = ThreadDTO | PostDTO | CommentDTO


class FunctionProvider(abc.ABC):
    """函数提供者接口。"""

    @abc.abstractmethod
    async def execute(self, name: str, data: ReviewData, args: list[Any], kwargs: dict[str, Any]) -> Any:
        """执行函数。

        Args:
            name: 函数名称。
            data: 数据对象 (ThreadDTO/PostDTO/CommentDTO)。
            args: 位置参数。
            kwargs: 关键字参数。

        Returns:
            Any: 函数执行结果。
        """


class LocalFunctionProvider(FunctionProvider):
    """本地函数提供者，基于注册表。"""

    async def execute(self, name: str, data: ReviewData, args: list[Any], kwargs: dict[str, Any]) -> Any:
        func = rule_functions.get_function(name)
        if not func:
            return None
        try:
            if inspect.iscoroutinefunction(func):
                return await func(data, *args, **kwargs)
            return func(data, *args, **kwargs)
        except Exception as e:
            logger.error("Error executing local function {}: {}", name, e)
            return None


class RpcFunctionProvider(FunctionProvider):
    """RPC 函数提供者，通过 gRPC 调用远程服务。"""

    def __init__(self, target: str, timeout: float = 5.0) -> None:
        """
        初始化 gRPC 客户端。

        Args:
            target: gRPC 服务地址 (例如 'localhost:50051')。
            timeout: 超时时间 (秒)。
        """
        self.target = target
        self.timeout = timeout
        self.channel = grpc.aio.insecure_channel(target)
        self.stub = review_service_pb2_grpc.ReviewFunctionServiceStub(self.channel)  # type: ignore

    async def execute(self, name: str, data: ReviewData, args: list[Any], kwargs: dict[str, Any]) -> Any:
        # 序列化数据
        data_json = data.model_dump_json()

        request = review_service_pb2.ExecuteRequest(  # type: ignore
            function_name=name,
            data_json=data_json,
            args_json=orjson.dumps(args).decode("utf-8"),
            kwargs_json=orjson.dumps(kwargs).decode("utf-8"),
        )

        try:
            response = await self.stub.Execute(request, timeout=self.timeout)
            if response.success:
                return orjson.loads(response.result_json)
            else:
                logger.warning("Remote function {} failed: {}", name, response.error_message)
                return None
        except grpc.RpcError as e:
            logger.error("gRPC call failed for {}: {}", name, e)
            return None
        except Exception as e:
            logger.error("Unexpected error in gRPC call {}: {}", name, e)
            return None

    async def close(self) -> None:
        await self.channel.close()


class HybridFunctionProvider(FunctionProvider):
    """混合函数提供者。

    优先查找本地注册表，如果未找到则调用远程 RPC。
    """

    def __init__(self, rpc_target: str, rpc_timeout: float = 5.0) -> None:
        self.local = LocalFunctionProvider()
        self.rpc = RpcFunctionProvider(rpc_target, rpc_timeout)

    async def execute(self, name: str, data: ReviewData, args: list[Any], kwargs: dict[str, Any]) -> Any:
        if rule_functions.get_function(name):
            return await self.local.execute(name, data, args, kwargs)

        return await self.rpc.execute(name, data, args, kwargs)

    async def close(self) -> None:
        await self.rpc.close()
