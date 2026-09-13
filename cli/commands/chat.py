import json

def run(args, client):
    if args.clear:
        client.delete(f"/llm/{args.device}/history")
        print(f"cleared chat history for '{args.device}'")
        return

    if args.message:
        _send(client, args.device, args.model, args.message)
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

        _send(client, args.device, args.model, user_input)

def _send(client, device_id: str, model: str, message: str) -> None:
    print("assistant> ", end="", flush=True)
    for line in client.stream_post(
        f"/llm/{device_id}/chat", {"model": model, "message": message, "stream": True}
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