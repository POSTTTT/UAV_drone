"""Natural-language drone pilot: a local LLM (Ollama by default) + ArduPilot SITL.

Works with any server that speaks the OpenAI-compatible chat API with tool calling:
Ollama, LM Studio, llama.cpp server, vLLM, or a hosted provider.

Usage:
    python agent.py                                   # interactive chat, Ollama on the Mac host
    python agent.py "take off to 5 m and land"        # single instruction
    python agent.py --model llama3.1:8b --base-url http://192.168.1.10:11434/v1
"""

import argparse
import json
import os
import sys

from openai import APIConnectionError, APIStatusError, OpenAI

from tools import SYSTEM_PROMPT, TOOL_SCHEMAS, DroneTools
from vehicle import Vehicle, VehicleError

DEFAULT_BASE_URL = os.environ.get("LLM_BASE_URL", "http://192.168.64.1:11434/v1")  # Ollama on the Mac host
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "qwen3:8b")
MAX_STEPS = 25  # tool calls per instruction, protects against a model stuck in a loop


def run_turn(client, model, tools, messages, user_text):
    """Send one operator instruction and let the model call tools until it answers."""
    messages.append({"role": "user", "content": user_text})
    for _ in range(MAX_STEPS):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_SCHEMAS,
            temperature=0,
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if not message.tool_calls:
            print(f"\nAgent: {message.content or '(no reply)'}")
            return

        if message.content and message.content.strip():
            print(f"\nAgent: {message.content.strip()}")
        for call in message.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
            except ValueError as e:
                result, is_error = f"Error: arguments were not valid JSON ({e}).", True
            else:
                print(f"  -> {name}({json.dumps(args)})")
                result, is_error = tools.call(name, args)
            if is_error:
                print(f"     ! {result[:200]}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    print(f"\nStopped after {MAX_STEPS} tool calls without a final answer. "
          "Check the drone in QGroundControl/MAVProxy.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("instruction", nargs="*", help="run a single instruction and exit")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"model name on the server (default: {DEFAULT_MODEL}, env LLM_MODEL)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help=f"OpenAI-compatible endpoint (default: {DEFAULT_BASE_URL}, env LLM_BASE_URL)")
    parser.add_argument("--api-key", default=os.environ.get("LLM_API_KEY", "ollama"),
                        help="API key if the server needs one (env LLM_API_KEY; Ollama ignores it)")
    parser.add_argument("--connect", default="tcp:127.0.0.1:5762",
                        help="MAVLink connection string (default: SITL's spare port tcp:127.0.0.1:5762)")
    args = parser.parse_args()

    print(f"Connecting to vehicle on {args.connect} ...")
    try:
        vehicle = Vehicle(args.connect)
    except (VehicleError, OSError) as e:
        sys.exit(f"Could not connect: {e}")
    print(f"Connected. Mode {vehicle.mode}, armed={vehicle.armed}")
    print(f"LLM: {args.model} at {args.base_url}")

    client = OpenAI(base_url=args.base_url, api_key=args.api_key, timeout=600)
    tools = DroneTools(vehicle)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    try:
        if args.instruction:
            run_turn(client, args.model, tools, messages, " ".join(args.instruction))
            return
        print("Type an instruction for the drone (e.g. 'take off to 10 m and fly 20 m north'). "
              "Ctrl+C or 'quit' to exit.")
        while True:
            try:
                text = input("\nYou: ").strip()
            except EOFError:
                break
            if text.lower() in {"quit", "exit"}:
                break
            if text:
                run_turn(client, args.model, tools, messages, text)
    except KeyboardInterrupt:
        print("\nInterrupted. The drone keeps its current mode; use QGroundControl or MAVProxy if needed.")
    except APIConnectionError:
        sys.exit(f"Cannot reach the LLM server at {args.base_url}. Is Ollama running? (ollama serve)")
    except APIStatusError as e:
        hint = f" Try: ollama pull {args.model}" if e.status_code == 404 else ""
        sys.exit(f"LLM server error {e.status_code}: {e.message}.{hint}")
    finally:
        vehicle.close()


if __name__ == "__main__":
    main()
