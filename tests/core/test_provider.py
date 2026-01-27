from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.provider import HybridFunctionProvider, LocalFunctionProvider, RpcFunctionProvider
from src.core.registry import rule_functions


@pytest.fixture
def clean_registry():
    original = rule_functions._functions.copy()
    rule_functions.clear()
    yield
    rule_functions._functions = original


@pytest.fixture
def mock_dto():
    dto = MagicMock()
    dto.model_dump.return_value = {"id": 1}
    dto.model_dump_json.return_value = '{"id": 1}'
    return dto


@pytest.mark.asyncio
async def test_local_provider_execute(clean_registry, mock_dto):
    @rule_functions.register("add")
    def add(data, a, b):
        return a + b

    provider = LocalFunctionProvider()
    result = await provider.execute("add", mock_dto, [1, 2], {})
    assert result == 3


@pytest.mark.asyncio
async def test_local_provider_unknown(clean_registry, mock_dto):
    provider = LocalFunctionProvider()
    # Implementation returns None for unknown
    result = await provider.execute("unknown", mock_dto, [], {})
    assert result is None


@pytest.mark.asyncio
async def test_rpc_provider(mock_dto):
    with (
        patch("src.core.provider.grpc.aio.insecure_channel"),
        patch("src.core.provider.review_service_pb2_grpc.ReviewFunctionServiceStub") as mock_stub,
    ):
        mock_stub_instance = AsyncMock()
        mock_stub.return_value = mock_stub_instance

        provider = RpcFunctionProvider("localhost:50051")

        # Mock success response
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.result_json = "42"
        mock_stub_instance.Execute.return_value = mock_response

        result = await provider.execute("remote_calc", mock_dto, [], {})
        assert result == 42

        # Check calling convention
        mock_stub_instance.Execute.assert_called_once()


@pytest.mark.asyncio
async def test_local_provider_exception(clean_registry, mock_dto):
    @rule_functions.register("fail")
    def fail(data):
        raise ValueError("Oops")

    provider = LocalFunctionProvider()
    # Should catch exception and return None
    result = await provider.execute("fail", mock_dto, [], {})
    assert result is None


@pytest.mark.asyncio
async def test_rpc_provider_errors(mock_dto):
    import grpc

    with (
        patch("src.core.provider.grpc.aio.insecure_channel"),
        patch("src.core.provider.review_service_pb2_grpc.ReviewFunctionServiceStub") as mock_stub_cls,
    ):
        mock_stub = AsyncMock()
        mock_stub_cls.return_value = mock_stub

        provider = RpcFunctionProvider("localhost:1234")

        # 1. RPC Error
        mock_stub.Execute.side_effect = grpc.RpcError("RPC Failed")
        result = await provider.execute("func", mock_dto, [], {})
        assert result is None

        # 2. Other Exception
        mock_stub.Execute.side_effect = Exception("General Error")
        result = await provider.execute("func", mock_dto, [], {})
        assert result is None

        # 3. Response failure (success=False)
        mock_stub.Execute.side_effect = None
        mock_response = MagicMock(success=False, error_message="Remote error")
        mock_stub.Execute.return_value = mock_response

        result = await provider.execute("func", mock_dto, [], {})
        assert result is None


@pytest.mark.asyncio
async def test_hybrid_provider_close():
    with patch("src.core.provider.RpcFunctionProvider") as mock_rpc_cls:
        mock_rpc = AsyncMock()
        mock_rpc.close = AsyncMock()
        mock_rpc_cls.return_value = mock_rpc

        provider = HybridFunctionProvider("target")
        await provider.close()

        mock_rpc.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_hybrid_provider(clean_registry, mock_dto):
    # Setup local function
    @rule_functions.register("local_f")
    def local_f(data):
        return "local"

    with patch("src.core.provider.RpcFunctionProvider") as mock_rpc_class:
        mock_rpc_instance = MagicMock()
        mock_rpc_instance.execute = AsyncMock(return_value="remote")
        mock_rpc_class.return_value = mock_rpc_instance

        provider = HybridFunctionProvider("target")

        # 1. Local hit
        result = await provider.execute("local_f", mock_dto, [], {})
        assert result == "local"
        mock_rpc_instance.execute.assert_not_called()

        # 2. Local miss -> Remote
        result = await provider.execute("remote_f", mock_dto, [], {})
        assert result == "remote"
        mock_rpc_instance.execute.assert_called_once()
