import json

def run(args, client):
    messages = []

    if args.message:
        messages.append({"role": "user", "content": args.message})
        _send(client, args.device, args.model, messages)
        return

    print(f"Chatting with '{args.model}' on '{args.device}'. Type 'exit' to quit.")
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

        messages.append({"role": "user", "content": user_input})
        reply = _send(client, args.device, args.model, messages)
        messages.append({"role": "assistant", "content": reply})

def _send(client, device_id: str, model: str, messages: list[dict]) -> str:
    print("assistant> ", end="", flush=True)
    chunks = []
    for line in client.stream_post(
        f"/llm/{device_id}/chat", {"model": model, "messages": messages, "stream": True}
    ):
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: ") :])
        if "error" in payload:
            print(f"[error: {payload['error']}]")
            return ""
        content = payload.get("message", {}).get("content", "")
        if content:
            print(content, end="", flush=True)
            chunks.append(content)
        if payload.get("done"):
            break
    print()
    return "".join(chunks)