import pytest
import base64
import json
import asyncio
import signal
from unittest.mock import MagicMock, Mock, patch, AsyncMock
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart, ToolCallPart
from pydantic_ai import DeferredToolRequests
from pydantic_ai.models.test import TestModel
from ag_ui.core.types import RunAgentInput, TextInputContent, BinaryInputContent
from agent_server import (
    parse_data_url, evaluate_expression, dangerous_tool, 
    process_text_attachment, process_binary_attachment, 
    tool_schema_to_a2ui, make_meme, create_agent, make_injector_stream_fn,
    Session, sessions, ping_all_sessions, lifespan, app, generated_memes,
    process_attachments, stream_agent_response, Dependencies, StateDeps,
    agent_run, instrument
)

client = TestClient(app)

import sys

def test_instrument():
    from agent_server import instrument
    # We call instrument to set up the provider
    instrument("test_service")
    
    from opentelemetry import trace
    tracer = trace.get_tracer("test_tracer")
    
    # Create a span to ensure CustomConsoleSpanExporter.export is called
    with tracer.start_as_current_span("test_span"):
        pass
        
    # Force flush to process the batch and call export()
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[attr-defined]

@pytest.mark.asyncio
async def test_agent_run_on_complete_callback():
    token = "test_on_complete_token"
    agent = create_agent()
    mock_session = Session(agent=agent, queue=asyncio.Queue())
    sessions[token] = mock_session

    request = MagicMock(spec=Request)
    run_input = MagicMock(spec=RunAgentInput)
    run_input.state = None
    
    callback_executed = False

    with patch("agent_server.stream_agent_response") as mock_stream:
        async def mock_gen(*args, **kwargs):
            nonlocal callback_executed
            on_complete = args[4] # on_complete_callback is the 5th positional arg
            deferred_reqs = args[5] # deferred_tool_requests is the 6th positional arg

            # Simulate a result with DeferredToolRequests
            mock_result = MagicMock()
            mock_result.output = DeferredToolRequests()

            # Add a real ToolCallPart so isinstance works
            real_part = ToolCallPart(
                tool_call_id="test-tool-id",
                tool_name="test_tool",
                args={"arg1": "val1"}
            )

            # Use a real ModelResponse (from pydantic_ai.messages)
            from pydantic_ai.messages import ModelResponse
            mock_result.response = ModelResponse(parts=[real_part])

            if on_complete:
                on_complete(mock_result)
                callback_executed = True
                    
            yield "data: ok\n\n"

            
        mock_stream.side_effect = mock_gen
        
        response = await agent_run(request, run_input, token)
        gen = cast(AsyncGenerator[str, None], response.body_iterator)
        await anext(gen)
        
        assert callback_executed
        
        # Check that deferred_tool_requests was populated
        assert mock_stream.call_args is not None
        deferred_reqs_passed = mock_stream.call_args[0][5]
        assert "test-tool-id" in deferred_reqs_passed
        assert deferred_reqs_passed["test-tool-id"]["tool_name"] == "test_tool"
        
        del sessions[token]

@pytest.mark.asyncio
async def test_agent_run_invalid_token():
    request = MagicMock(spec=Request)
    run_input = MagicMock(spec=RunAgentInput)
    with pytest.raises(HTTPException) as excinfo:
        await agent_run(request, run_input, "invalid_token")
    assert excinfo.value.status_code == 404

@pytest.mark.asyncio
async def test_agent_run_cancel_task():
    token = "test_cancel_token"
    mock_session = Session(agent=MagicMock(), queue=asyncio.Queue())
    
    # Setup a dummy task that raises CancelledError when awaited
    async def dummy_task_fn():
        raise asyncio.CancelledError()  # pragma: no cover
        
    dummy_task = asyncio.create_task(dummy_task_fn())
    mock_session.current_task = dummy_task
    sessions[token] = mock_session
    
    request = MagicMock(spec=Request)
    run_input = MagicMock(spec=RunAgentInput)
    run_input.state = None
    
    with patch("agent_server.stream_agent_response") as mock_stream:
        # Mock the stream to just yield one item
        async def mock_gen(*args, **kwargs):
            yield "data: ok\n\n"
        mock_stream.side_effect = mock_gen
        
        response = await agent_run(request, run_input, token)
        gen = cast(AsyncGenerator[str, None], response.body_iterator)
        
        chunk = await anext(gen)
        assert chunk == "data: ok\n\n"
        
        # Verify the task was cancelled
        assert dummy_task.cancelled() or dummy_task.done()
        
        # Clean up
        del sessions[token]

@pytest.mark.asyncio
async def test_agent_run_manual_call():
    token = "test_manual_token"
    agent = create_agent()
    mock_session = Session(agent=agent, queue=asyncio.Queue())
    sessions[token] = mock_session
    
    request = MagicMock(spec=Request)
    run_input = MagicMock(spec=RunAgentInput)
    run_input.state = {
        "manual_tool_call": {
            "name": "evaluate_expression",
            "args": {"expression": "2+2"}
        }
    }
    
    with patch("agent_server.stream_agent_response") as mock_stream:
        async def mock_gen(*args, **kwargs):
            # Verify the agent passed to stream_agent_response has the injector model
            passed_agent = args[2]
            assert passed_agent.model.model_name == "manual-tool-injector"
            yield "data: ok\n\n"
        mock_stream.side_effect = mock_gen
        
        response = await agent_run(request, run_input, token)
        gen = cast(AsyncGenerator[str, None], response.body_iterator)
        
        chunk = await anext(gen)
        assert chunk == "data: ok\n\n"
        
        # Clean up
        del sessions[token]

@pytest.mark.asyncio
async def test_agent_run_generator_exit():
    token = "test_exit_token"
    mock_session = Session(agent=MagicMock(), queue=asyncio.Queue())
    sessions[token] = mock_session
    
    request = MagicMock(spec=Request)
    run_input = MagicMock(spec=RunAgentInput)
    run_input.state = None
    
    state_dict = {}
    mock_ag_ui_events = MagicMock()
    mock_ag_ui_events.aclose = AsyncMock()
    
    with patch("agent_server.stream_agent_response") as mock_stream:
        async def mock_gen(*args, **kwargs):
            # args[6] is state dictionary
            args[6]["ag_ui_events"] = mock_ag_ui_events
            yield "data: chunk1\n\n"
            raise asyncio.CancelledError()
            
        mock_stream.side_effect = mock_gen
        
        response = await agent_run(request, run_input, token)
        gen = cast(AsyncGenerator[str, None], response.body_iterator)
        
        chunk = await anext(gen)
        assert chunk == "data: chunk1\n\n"
        
        with pytest.raises(asyncio.CancelledError):
            await anext(gen)
            
        # Verify aclose was called
        mock_ag_ui_events.aclose.assert_called_once()
        
        # Clean up
        del sessions[token]

@pytest.mark.asyncio
async def test_stream_agent_response():
    from unittest.mock import patch, MagicMock
    token = "test_stream_token"
    agent = create_agent()
    deps = StateDeps(Dependencies())
    
    # 1. Setup mock run_input
    mock_msg = MagicMock()
    mock_msg.role = "user"
    mock_msg.content = "User prompt"
    
    text_data = base64.b64encode(b"Attachment data").decode("utf-8")
    run_input = MagicMock(spec=RunAgentInput)
    run_input.messages = [mock_msg]
    run_input.state = {
        "deferred_tool_approvals": {"tool1": True},
        "attachments": {"f.txt": f"data:text/plain;base64,{text_data}"},
        "disabled_tools": ["dangerous_tool"]
    }
    
    # 2. Mock run_ag_ui generator
    async def mock_run_ag_ui(*args, **kwargs):
        yield 'data: {"type": "RUN_STARTED"}\n\n'
        yield 'data: {"type": "RUN_FINISHED"}\n\n'
        yield 'data: {"type": "OTHER"}\n\n'
        
    on_complete_called = False
    def on_complete(result, reqs):
        nonlocal on_complete_called
        # The run_ag_ui generator is mocked to yield immediately, bypassing the real on_complete callback
        on_complete_called = True  # pragma: no cover
        
    deferred_requests = {"tool2": "args"}
    state_dict = {}
    
    with patch("agent_server.run_ag_ui", side_effect=mock_run_ag_ui):
        gen = stream_agent_response(
            token=token,
            run_input=run_input,
            agent=agent,
            deps=deps,
            on_complete_callback=on_complete,
            deferred_tool_requests=deferred_requests,
            state=state_dict
        )
        
        # 1. RUN_STARTED
        first_chunk = await anext(gen)
        assert "RUN_STARTED" in first_chunk
        
        # 2. CustomEvent: instructions (because len(run_input.messages) == 1)
        instr_chunk = await anext(gen)
        assert '"name": "instructions"' in instr_chunk
        
        # 3. CustomEvent: attachments
        att_chunk = await anext(gen)
        assert '"name": "attachments"' in att_chunk
        assert "f.txt" in att_chunk
        
        # 4. CustomEvent: deferred_tool_requests (yielded before RUN_FINISHED is passed through)
        deferred_chunk = await anext(gen)
        assert '"name": "deferred_tool_requests"' in deferred_chunk
        assert "tool2" in deferred_chunk
        
        # 5. RUN_FINISHED
        finished_chunk = await anext(gen)
        assert "RUN_FINISHED" in finished_chunk
        
        # 6. OTHER
        other_chunk = await anext(gen)
        assert "OTHER" in other_chunk
        
        with pytest.raises(StopAsyncIteration):
            await anext(gen)

def test_process_attachments():
    # Setup mock input with attachments
    text_data = base64.b64encode(b"Hello from file").decode("utf-8")
    binary_data = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("utf-8")
    
    attachments = {
        "hello.txt": f"data:text/plain;base64,{text_data}",
        "image.png": f"data:image/png;base64,{binary_data}",
        "invalid": "not-a-data-url"
    }
    
    # Mock message
    mock_msg = MagicMock()
    mock_msg.role = "user"
    mock_msg.content = "User prompt"
    
    run_input = MagicMock(spec=RunAgentInput)
    run_input.state = {"attachments": attachments}
    run_input.messages = [mock_msg]
    
    result = process_attachments(run_input)
    
    # Verify result dictionary
    assert "hello.txt" in result
    assert "image.png" in result
    assert "invalid" not in result
    
    # Verify content was updated
    assert isinstance(mock_msg.content, list)
    assert len(mock_msg.content) == 3 # original text + 2 attachments
    
    assert any(isinstance(c, TextInputContent) and "hello.txt" in c.text for c in mock_msg.content)
    assert any(isinstance(c, BinaryInputContent) and c.filename == "image.png" for c in mock_msg.content)

def test_process_attachments_no_user_messages():
    run_input = MagicMock(spec=RunAgentInput)
    run_input.state = {"attachments": {"f.txt": "data:text/plain;base64,WA=="}}
    
    # Message is not a user role
    mock_msg = MagicMock()
    mock_msg.role = "system"
    run_input.messages = [mock_msg]
    
    result = process_attachments(run_input)
    assert result == {}
    
def test_process_attachments_list_content():
    run_input = MagicMock(spec=RunAgentInput)
    run_input.state = {"attachments": {"f.txt": "data:text/plain;base64,WA=="}}
    
    mock_msg = MagicMock()
    mock_msg.role = "user"
    existing_content = TextInputContent(text="existing list")
    mock_msg.content = [existing_content]
    run_input.messages = [mock_msg]
    
    result = process_attachments(run_input)
    assert "f.txt" in result
    assert isinstance(mock_msg.content, list)
    assert len(mock_msg.content) == 2
    assert mock_msg.content[0] == existing_content
    
def test_process_attachments_unknown_content_type():
    run_input = MagicMock(spec=RunAgentInput)
    run_input.state = {"attachments": {"f.txt": "data:text/plain;base64,WA=="}}
    
    mock_msg = MagicMock()
    mock_msg.role = "user"
    mock_msg.content = None # Not a string, not a list
    run_input.messages = [mock_msg]
    
    result = process_attachments(run_input)
    assert "f.txt" in result
    assert isinstance(mock_msg.content, list)
    assert len(mock_msg.content) == 1

def test_process_attachments_no_messages():
    run_input = MagicMock(spec=RunAgentInput)
    run_input.state = {"attachments": {"f.txt": "data:text/plain;base64,WA=="}}
    run_input.messages = []
    
    result = process_attachments(run_input)
    assert result == {}

def test_serve_meme():
    # Test 404
    response = client.get("/memes/invalid_id")
    assert response.status_code == 404
    
    # Generate a real meme to test 200 OK
    result_json = make_meme("test", "serve")
    result = json.loads(result_json)
    meme_id = result["meme_id"]
    
    try:
        # Test 200
        response = client.get(f"/memes/{meme_id}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
    finally:
        # Cleanup
        meme_path = generated_memes.get(meme_id)
        if meme_path and meme_path.exists():
            meme_path.unlink()
        if meme_id in generated_memes:
            del generated_memes[meme_id]

from fastapi import Request
from agent_server import events

from typing import AsyncGenerator, cast

@pytest.mark.asyncio
async def test_events_sse():
    # Call the endpoint directly to avoid cross-thread event loop issues with asyncio.Queue
    request = MagicMock(spec=Request)
    response = await events(request)
    
    assert response.media_type == "text/event-stream"
    
    # Get the async generator from the StreamingResponse
    gen = cast(AsyncGenerator[str, None], response.body_iterator)
    
    # 1. First event: agent info
    first_chunk = await anext(gen)
    assert first_chunk.startswith("data: ")
    data = json.loads(first_chunk.strip()[6:])
    assert "agent" in data
    assert "available_tools" in data
    
    token = data["agent"].split("token=")[1]
    assert token in sessions
    session = sessions[token]
    
    # 2. Custom event
    session.queue.put_nowait({"hello": "world"})
    custom_chunk = await anext(gen)
    assert json.loads(custom_chunk.strip()[6:]) == {"hello": "world"}
    
    # 3. Shutdown event
    session.queue.put_nowait({"die": True})
    die_chunk = await anext(gen)
    assert die_chunk == "event: die\ndata: shutdown\n\n"
    
    # 4. Stream should terminate
    with pytest.raises(StopAsyncIteration):
        await anext(gen)
        
    # Verify cleanup happened after stream closed
    assert token not in sessions

@pytest.mark.asyncio
async def test_events_sse_cancelled():
    request = MagicMock(spec=Request)
    response = await events(request)
    gen = cast(AsyncGenerator[str, None], response.body_iterator)
    
    first_chunk = await anext(gen)
    data = json.loads(first_chunk.strip()[6:])
    token = data["agent"].split("token=")[1]
    
    # Throw a CancelledError into the generator to simulate disconnect.
    # The generator catches it and exits gracefully, which results in StopAsyncIteration
    with pytest.raises(StopAsyncIteration):
        await gen.athrow(asyncio.CancelledError())
        
    assert token not in sessions

@pytest.mark.asyncio
async def test_events_sse_task_cancellation():
    request = MagicMock(spec=Request)
    response = await events(request)
    gen = cast(AsyncGenerator[str, None], response.body_iterator)
    
    first_chunk = await anext(gen)
    data = json.loads(first_chunk.strip()[6:])
    token = data["agent"].split("token=")[1]
    session = sessions[token]
    
    # Assign a dummy task
    dummy_task = MagicMock()
    dummy_task.done.return_value = False
    session.current_task = dummy_task
    
    session.queue.put_nowait({"die": True})
    await anext(gen) # consume die event
    with pytest.raises(StopAsyncIteration):
        await anext(gen)
        
    dummy_task.cancel.assert_called_once()
    assert token not in sessions

@pytest.mark.asyncio
async def test_lifespan():
    app_mock = Mock(spec=FastAPI)
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
        
        async with lifespan(app_mock):
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
