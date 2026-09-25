import json

_CLI_CONVERSATION_TITLE = "cli session"

def _resolve_conversation(client, device_id: str) -> str:
    """The CLI has no notion of picking between chats like the web UI does,
    so it just reuses (or creates) one dedicated conversation per device,
    keeping history remembered across runs"""
    data = client.get(f"/llm/{device_id}/conversations")
    for entry in data.get("conversations", []):
        if entry.get("title") == _CLI_CONVERSATION_TITLE:
            return entry["id"]

    entry = client.post(f"/llm/{device_id}/conversations", {"title": _CLI_CONVERSATION_TITLE})
    return entry["id"]

def run(args, client):
    conversation_id = _resolve_conversation(client, args.device)
    if args.clear:
        client.delete(f"/llm/{args.device}/conversations/{conversation_id}/history")
        print(f"cleared chat history for '{args.device}'")
        return

    if args.message:
        _send(client, args.device, conversation_id, args.model, args.message)
        return

    print(f"Chatting with '{args.model}' on '{args.device}'. Type 'exit' to quit.")
    print("(history is remembered by the hub across runs; use --clear to reset it)")
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue

        _send(client, args.device, conversation_id, args.model, user_input)

def _send(client, device_id: str, conversation_id: str, model: str, message: str) -> None:
    print("assistant> ", end="", flush=True)
    for line in client.stream_post(
        f"/llm/{device_id}/conversations/{conversation_id}/chat",
        {"model": model, "message": message, "stream": True},
    ):
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: ") :])
        if "error" in payload:
            print(f"[error: {payload['error']}]")
            return
        content = payload.get("message", {}).get("content", "")
        if content:
            print(content, end="", flush=True)

        if payload.get("done"):
            break
    print()