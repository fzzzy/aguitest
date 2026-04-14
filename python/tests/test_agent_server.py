import pytest
import base64
import json
import asyncio
from unittest.mock import MagicMock
from pathlib import Path
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel
from agent_server import (
    parse_data_url, evaluate_expression, dangerous_tool, 
    process_text_attachment, process_binary_attachment, 
    tool_schema_to_a2ui, make_meme, create_agent, make_injector_stream_fn,
    Session, sessions, ping_all_sessions, lifespan
)
import signal
from fastapi import FastAPI

@pytest.mark.asyncio
async def test_lifespan():
    from unittest.mock import patch, Mock, MagicMock
    
    app = Mock(spec=FastAPI)
    mock_loop = Mock()
    
    class DummyTask:
        def __init__(self):
            self.cancelled = False
        def cancel(self):
            self.cancelled = True

    mock_task = DummyTask()
    
    with patch("asyncio.get_running_loop", return_value=mock_loop), \
         patch("signal.getsignal", return_value=Mock()), \
         patch("asyncio.create_task", return_value=mock_task) as mock_create_task:
        
        async with lifespan(app):
            # Verify signal handlers were added for SIGTERM and SIGINT
            assert mock_loop.add_signal_handler.call_count == 2
            
            # Verify ping task was created
            mock_create_task.assert_called_once()
            
            # Test the signal handler logic
            handler = mock_loop.add_signal_handler.call_args_list[0][0][1]
            queue = asyncio.Queue(maxsize=1)
            sessions["test_token"] = Session(agent=MagicMock(), queue=queue)
            
            try:
                handler()
                assert queue.qsize() == 1
                event = queue.get_nowait()
                assert event == {"die": True}
            finally:
                if "test_token" in sessions:
                    del sessions["test_token"]
            
        # Verify ping task was cancelled after yield
        assert mock_task.cancelled
        
        # Capture the real ping_all_sessions coroutine that was passed to create_task
        # and close it to prevent the "unawaited coroutine" warning.
        coro = mock_create_task.call_args[0][0]
        coro.close()
@pytest.mark.asyncio
async def test_ping_all_sessions():
    from unittest.mock import patch
    
    # Setup mock session
    queue = asyncio.Queue(maxsize=1)
    mock_session = Session(agent=MagicMock(), queue=queue)
    sessions["test_token"] = mock_session
    
    try:
        # Mock sleep to raise an exception after the first call to break the while True loop
        with patch("asyncio.sleep", side_effect=[None, Exception("Stop loop")]):
            with pytest.raises(Exception, match="Stop loop"):
                await ping_all_sessions()
        
        # Verify ping was put in queue
        assert queue.qsize() == 1
        event = queue.get_nowait()
        assert event == {"ping": True}
        
        # Test QueueFull branch
        queue.put_nowait({"already": "full"})
        with patch("asyncio.sleep", side_effect=[None, Exception("Stop loop")]):
            with pytest.raises(Exception, match="Stop loop"):
                await ping_all_sessions()
        # Should not raise asyncio.QueueFull due to try-except block
        
    finally:
        # Cleanup
        if "test_token" in sessions:
            del sessions["test_token"]

def test_create_agent():
    agent = create_agent()
    assert agent is not None
    # We just need to verify the agent was created properly without accessing typed internals
    assert agent.name is None or isinstance(agent.name, str)

@pytest.mark.asyncio
async def test_make_injector_stream_fn():
    class MockModel:
        async def request(self, messages, settings, params):
            class MockResponse:
                class MockPart:
                    content = "Mock summary"
                parts = [MockPart()]
            return MockResponse()

    mock_model = MockModel()
    injector_fn = make_injector_stream_fn("test_tool", '{"arg": "value"}', mock_model)
    
    # First call - should yield tool call delta
    messages = []
    info = MagicMock()
    info.model_settings = None
    info.model_request_parameters = None
    
    async_iter_1 = injector_fn(messages, info)
    result_1 = []
    async for item in async_iter_1:
        result_1.append(item)
        
    assert len(result_1) == 1
    assert 0 in result_1[0]
    assert result_1[0][0].name == "test_tool"
    assert result_1[0][0].json_args == '{"arg": "value"}'
    
    # Check that a UserPromptPart was injected
    assert len(messages) == 1
    assert isinstance(messages[0], ModelRequest)
    assert len(messages[0].parts) == 1
    assert "test_tool" in messages[0].parts[0].content
    
    # Second call - should yield mock model's string response
    messages = [messages[0]] # Simulate agent loop keeping history
    async_iter_2 = injector_fn(messages, info)
    result_2 = []
    async for item in async_iter_2:
        result_2.append(item)
        
    assert len(result_2) == 1
    assert result_2[0] == "Mock summary"
    # Note: messages should now have another injected user prompt, making it 2 items
    assert len(messages) == 2
def test_make_meme():
    result_json = make_meme("hello", "world")
    result = json.loads(result_json)
    assert "url" in result
    assert "meme_id" in result
    
    meme_id = result["meme_id"]
    meme_path = Path(__file__).parent.parent / "generated_memes" / f"meme_{meme_id}.png"
    assert meme_path.exists()
    
    # Cleanup
    meme_path.unlink()

def test_parse_data_url_valid():
    result = parse_data_url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB")
    assert result is not None
    media_type, b64 = result
    assert media_type == "image/png"
    assert b64 == "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"

def test_parse_data_url_invalid():
    assert parse_data_url("not a valid url") is None
    assert parse_data_url("data:image/png;base64") is None

def test_evaluate_expression():
    assert evaluate_expression("2 + 2") == "4"
    assert evaluate_expression("10 ** 2") == "100"
    
def test_evaluate_expression_error():
    result = evaluate_expression("1 / 0")
    assert "inf" in result

def test_evaluate_expression_invalid_syntax():
    result = evaluate_expression("2 + ")
    assert "Error evaluating expression" in result

def test_dangerous_tool():
    result = dangerous_tool("testing")
    assert result == "grfgvat"

def test_process_text_attachment():
    data = "Hello, AGUI!"
    b64_data = base64.b64encode(data.encode("utf-8")).decode("utf-8")
    
    result = process_text_attachment(b64_data, "hello.txt")
    
    assert 'name="hello.txt"' in result.text
    assert "Hello, AGUI!" in result.text
    assert "<file-attachment" in result.text

def test_process_binary_attachment():
    data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
    result = process_binary_attachment("image/png", data, "pixel.png")
    
    assert result.mime_type == "image/png"
    assert result.data == data
    assert result.filename == "pixel.png"

class MockSchema:
    def __init__(self, json_schema):
        self.json_schema = json_schema

class MockTool:
    def __init__(self, json_schema):
        self.function_schema = MockSchema(json_schema)

def test_tool_schema_to_a2ui_empty():
    tool = MockTool({})
    result = tool_schema_to_a2ui("empty_tool", tool)
    
    # Expect surfaceUpdate and beginRendering messages
    assert len(result) == 2
    surface_update = result[0]["surfaceUpdate"]
    assert surface_update["surfaceId"] == "empty_tool"
    assert len(surface_update["components"]) == 2 # Column container and Submit button

def test_tool_schema_to_a2ui_with_properties():
    schema = {
        "properties": {
            "name": {
                "title": "Name",
                "description": "The user name",
                "type": "string"
            },
            "age": {
                "title": "Age",
                "type": "integer"
            }
        },
        "required": ["name"]
    }
    tool = MockTool(schema)
    result = tool_schema_to_a2ui("user_form", tool)
    
    # Expect surfaceUpdate and beginRendering messages
    assert len(result) == 2
    surface_update = result[0]["surfaceUpdate"]
    
    # 4 components: form, name input, age input, submit button
    components = surface_update["components"]
    assert len(components) == 4
    
    name_field = next(c for c in components if c["id"] == "user_form-name")
    assert name_field["component"]["TextField"]["label"] == {"literalString": "name"}
    
    age_field = next(c for c in components if c["id"] == "user_form-age")
    assert age_field["component"]["TextField"]["label"] == {"literalString": "age"}
    
    begin_rendering = result[1]["beginRendering"]
    assert begin_rendering["root"] == "user_form-form"
    assert begin_rendering["surfaceId"] == "user_form"

def test_tool_schema_to_a2ui_boolean():
    schema = {
        "properties": {
            "active": {
                "type": "boolean"
            }
        }
    }
    tool = MockTool(schema)
    result = tool_schema_to_a2ui("boolean_tool", tool)
    
    surface_update = result[0]["surfaceUpdate"]
    components = surface_update["components"]
    
    active_field = next(c for c in components if c["id"] == "boolean_tool-active")
    assert "Checkbox" in active_field["component"]
    assert active_field["component"]["Checkbox"]["label"] == {"literalString": "active"}
    assert active_field["component"]["Checkbox"]["dataModelKey"] == "active"

