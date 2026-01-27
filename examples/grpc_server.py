import asyncio
import logging

import grpc
import orjson

from src.rpc import review_service_pb2, review_service_pb2_grpc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ReviewService(review_service_pb2_grpc.ReviewFunctionServiceServicer):
    async def Execute(self, request, context):  # noqa: N802
        func_name = request.function_name
        logger.info(f"Received request for function: {func_name}")

        try:
            data = orjson.loads(request.data_json)
            args = orjson.loads(request.args_json)
            kwargs = orjson.loads(request.kwargs_json)
        except orjson.JSONDecodeError as e:
            return review_service_pb2.ExecuteResponse(success=False, error_message=f"JSON decode error: {str(e)}")  # type: ignore

        # 执行逻辑
        result = None
        error = None

        try:
            if func_name == "ai_check_toxicity":
                result = await self._mock_ai_check(data)
            elif func_name == "echo":
                result = {"data": data, "args": args, "kwargs": kwargs}
            else:
                error = f"Function {func_name} not found"
        except Exception as e:
            error = f"Execution error: {str(e)}"
            logger.error(error)

        if error:
            return review_service_pb2.ExecuteResponse(success=False, error_message=error)  # type: ignore

        return review_service_pb2.ExecuteResponse(success=True, result_json=orjson.dumps(result).decode("utf-8"))  # type: ignore

    async def _mock_ai_check(self, data):
        await asyncio.sleep(1.0)  # 模拟 1秒 延迟
        text = data.get("text", "") or data.get("title", "")
        # 简单逻辑：包含 "违规" 判为违规
        is_toxic = "违规" in text
        logger.info(f"AI Check for text: '{text[:20]}...' -> Toxic: {is_toxic}")
        return is_toxic


async def serve():
    server = grpc.aio.server()
    review_service_pb2_grpc.add_ReviewFunctionServiceServicer_to_server(ReviewService(), server)
    listen_addr = "[::]:50051"
    server.add_insecure_port(listen_addr)
    logger.info(f"Starting gRPC server on {listen_addr}")
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
