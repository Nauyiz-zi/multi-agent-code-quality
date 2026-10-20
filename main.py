import argparse

from agent import run_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="代码审查 Agent")
    parser.add_argument("path", help="要审查的文件路径")
    parser.add_argument("--max-steps", type=int, default=8, help="Agent 最大步数")
    parser.add_argument("--output", help="把审查报告保存到指定文件")
    args = parser.parse_args()

    try:
        result = run_agent(args.path, max_steps=args.max_steps)
    except Exception as exc:
        print(f"运行失败：{exc}")
        return

    print("\n" + "=" * 60)
    print("审查报告")
    print("=" * 60)
    print(result["answer"])

    print("\n" + "=" * 60)
    print("Agent 执行轨迹")
    print("=" * 60)

    for item in result["trace"]:
        print(
            f"第 {item['step']} 步："
            f"{item['tool']} {item['arguments']} -> ok={item['ok']}"
        )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(result["answer"])
        print(f"\n报告已保存到：{args.output}")


if __name__ == "__main__":
    main()