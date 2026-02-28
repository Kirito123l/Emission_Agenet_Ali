"""
迁移知识库数据
从 rag_json_mcp 项目复制向量索引到 emission_agent
"""
import shutil
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parent.parent.parent  # Agent_MCP/
AGENT_ROOT = Path(__file__).resolve().parent.parent        # Agent_MCP/emission_agent/

def migrate_knowledge():
    """迁移知识库索引文件"""
    src = MCP_ROOT / "rag_json_mcp/knowledge/vector_index_v2"
    dst = AGENT_ROOT / "skills/knowledge/index"
    dst.mkdir(parents=True, exist_ok=True)

    files = [
        "dense_index.faiss",
        "sparse_embeddings.pkl",
        "chunk_ids.pkl",
    ]

    print("开始迁移知识库...")
    for f in files:
        src_file = src / f
        dst_file = dst / f
        if src_file.exists():
            shutil.copy(src_file, dst_file)
            print(f"[OK] 复制: {f} ({src_file.stat().st_size / 1024:.1f} KB)")
        else:
            print(f"[FAIL] 文件不存在: {src_file}")

    # 复制chunks
    chunks_src = MCP_ROOT / "rag_json_mcp/knowledge/annotated/chunks_optimized.jsonl"
    chunks_dst = dst / "chunks.jsonl"
    if chunks_src.exists():
        shutil.copy(chunks_src, chunks_dst)
        print(f"[OK] 复制: chunks.jsonl ({chunks_src.stat().st_size / 1024:.1f} KB)")
    else:
        print(f"[FAIL] 文件不存在: {chunks_src}")

    print("\n知识库迁移完成!")
    print(f"目标目录: {dst}")

if __name__ == "__main__":
    migrate_knowledge()
