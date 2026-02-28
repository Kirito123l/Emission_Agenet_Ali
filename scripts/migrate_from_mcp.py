import shutil
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parent.parent.parent  # Agent_MCP/
AGENT_ROOT = Path(__file__).resolve().parent.parent        # Agent_MCP/emission_agent/

def migrate():
    """迁移数据文件从MCP项目到Agent项目"""
    print("开始数据迁移...")

    # emission_factors
    print("\n1. 迁移排放因子数据...")
    src = MCP_ROOT / "moves_emission_mcp/data/query_factors/emission_matrix"
    dst = AGENT_ROOT / "skills/emission_factors/data/emission_matrix"
    dst.mkdir(parents=True, exist_ok=True)

    if src.exists():
        count = 0
        for f in src.glob("*.csv"):
            shutil.copy(f, dst)
            print(f"  复制: {f.name}")
            count += 1
        print(f"  完成: {count} 个文件")
    else:
        print(f"  警告: 源目录不存在 {src}")

    # micro_emission (TODO: Phase 5)
    print("\n2. 微观排放数据 (Phase 5)")
    # src = MCP_ROOT / "moves_emission_mcp/data/micro_emission"
    # dst = AGENT_ROOT / "skills/micro_emission/data"
    # ...

    # macro_emission (TODO: Phase 5)
    print("\n3. 宏观排放数据 (Phase 5)")
    # src = MCP_ROOT / "moves_emission_mcp/data/macro_emission"
    # dst = AGENT_ROOT / "skills/macro_emission/data"
    # ...

    # knowledge (TODO: Phase 5)
    print("\n4. 知识库数据 (Phase 5)")
    # src = MCP_ROOT / "rag_json_mcp/knowledge/vector_index_v2"
    # dst = AGENT_ROOT / "skills/knowledge/index"
    # ...

    print("\n迁移完成!")

if __name__ == "__main__":
    migrate()
