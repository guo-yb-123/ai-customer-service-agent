import os
import dashscope
from dashscope import TextEmbedding
import re
import config
import psycopg2
from psycopg2.extras import RealDictCursor
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "")
if not dashscope.api_key:
    import warnings
    warnings.warn("DASHSCOPE_API_KEY 未设置，向量检索功能不可用")

pg_config = config.VECTOR_PG_CONFIG


def split_long_text(text: str, chunk_size: int = 300) -> list[str]:
    if not text.strip():
        return []
    split_separators = ["。", "！", "？", "\n"]
    sep_pattern = "(" + "|".join(re.escape(s) for s in split_separators) + ")"
    seg_parts = re.split(sep_pattern, text)
    buffer = ""
    chunk_list = []
    i = 0
    while i < len(seg_parts):
        txt = seg_parts[i].strip()
        sep = seg_parts[i + 1] if (i + 1 < len(seg_parts)) else ""
        i += 2

        full_part = txt + sep
        if not full_part.strip():
            continue

        if len(buffer + full_part) > chunk_size:
            if buffer:
                chunk_list.append(buffer)
            # 单段超长强制切割
            if len(full_part) > chunk_size:
                for start in range(0, len(full_part), chunk_size):
                    chunk_list.append(full_part[start:start + chunk_size])
                buffer = ""
            else:
                buffer = full_part
        else:
            buffer += full_part
    if buffer:
        chunk_list.append(buffer)
    return chunk_list


def get_embedding(text: str) -> list[float]:
    if not text.strip():
        raise ValueError("向量化文本不能为空")
    try:
        resp = TextEmbedding.call(
            model=config.EMBEDDING_MODEL,
            input=text,
            dimension=config.EMBEDDING_DIM,
        )
        if resp.code:
            err_msg = resp.message if resp.message else "无错误详情"
            raise RuntimeError(f"向量接口调用失败：{err_msg}")
        embedding_data = resp.output["embeddings"][0]["embedding"]
        return embedding_data
    except Exception as e:
        raise RuntimeError(f"获取embedding异常：{str(e)}") from e


def batch_get_embedding(text_list: list[str]) -> list[list[float]]:
    valid_texts = [t.strip() for t in text_list if t.strip()]
    if not valid_texts:
        return []
    try:
        resp = TextEmbedding.call(
            model=config.EMBEDDING_MODEL,
            input=valid_texts,
            dimension=config.EMBEDDING_DIM,
        )
        if resp.code:
            msg = resp.message if resp.message else "接口返回业务错误，无详细描述"
            raise RuntimeError(f"批量向量接口调用失败:{msg}")
        emb_map = [item["embedding"] for item in resp.output["embeddings"]]
        return emb_map
    except Exception as e:
        raise RuntimeError(f"批量获取embedding异常:{str(e)}") from e


def insert_knowledge(category: str, title: str, full_content: str):
    chunks = split_long_text(full_content, chunk_size=300)
    if not chunks:
        logger.warning("无有效文档片段")
        return
    embeddings = batch_get_embedding(chunks)
    conn = psycopg2.connect(**pg_config)
    cur = conn.cursor()
    insert_sql = """
            INSERT INTO knowledge_doc (category, title, content, embedding)
            VALUES (%s, %s, %s, %s::vector(1024))
        """
    for chunk, vec in zip(chunks, embeddings):
        cur.execute(insert_sql, (category, title, chunk, vec))
    conn.commit()
    cur.close()
    conn.close()
    logger.info("入库完成, 共 %s 个文本片段", len(chunks))


def retrieve_knowledge(question: str, top_n: int = 2) -> list[dict]:
    """根据用户问题检索知识库，混合检索，返回匹配文档"""
    query_vec = get_embedding(question)
    vec_str = f"[{','.join(map(str, query_vec))}]"

    conn = psycopg2.connect(**pg_config)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 【修复2】将 LIMIT 3 换成动态传参，向量查多一部分，避免联合查询后不足 top_n
    vec_limit = top_n * 2
    search_sql = """
        WITH vec_res AS (
            SELECT id, category, title, content, embedding <-> %s AS dist
            FROM knowledge_doc
            ORDER BY dist ASC LIMIT %s
        ),
        text_res AS (
            SELECT id, category, title, content, 0.5 AS dist
            FROM knowledge_doc
            WHERE to_tsvector('simple', content) @@ to_tsquery('simple', %s)
            LIMIT %s
        )
        SELECT DISTINCT id, category, title, content, dist
        FROM vec_res UNION SELECT id, category, title, content, dist FROM text_res
        ORDER BY dist ASC LIMIT %s;
    """
    keyword = " & ".join([w for w in re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9]+", question) if len(w) >= 2])

    # 注意参数顺序：vec_str, vec_limit, keyword, vec_limit(给text_res用), top_n(最终结果)
    cur.execute(search_sql, (vec_str, vec_limit, keyword, vec_limit, top_n))
    res = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(row) for row in res]


def similar_search(query_text: str, top_k: int = 3, threshold: float = 0.8):
    # 建议这个函数保留，作为纯向量检索的备用（比如给测试用）
    query_vec = get_embedding(query_text)
    conn = psycopg2.connect(**pg_config)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql = """
                SELECT category, title, content, embedding <=> %s::vector(1024) AS score
                FROM knowledge_doc
                WHERE embedding <=> %s::vector(1024) < %s
                ORDER BY score ASC
                LIMIT %s;
                        """
            cur.execute(sql, (query_vec, query_vec, threshold, top_k))
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


def build_rag_prompt(user_query: str, top_k: int = 2):
    """混合检索 + 相关性重排 + 检索质量自检"""
    docs = retrieve_knowledge(user_query, top_n=top_k * 2)

    # Re-rank：用余弦相似度重排序
    if docs:
        query_vec = get_embedding(user_query)
        for doc in docs:
            try:
                doc_vec = get_embedding(doc["content"])
                doc["_rerank_score"] = cosine_similarity_relevance(query_vec, doc_vec)
            except Exception:
                doc["_rerank_score"] = 0.0
        docs.sort(key=lambda d: d.get("_rerank_score", 0), reverse=True)
        docs = docs[:top_k]

    # 检索质量自检：最好文档的相似度太低 → 返回空
    if docs and docs[0].get("_rerank_score", 0) < 0.5:
        empty_prompt = f"""你是一个严谨的AI客服专员。请仅根据下面参考资料回答用户问题，禁止编造信息。
参考资料：未找到与\"{user_query}\"高度相关的知识库内容。
用户问题：{user_query}
请直接回答\"抱歉，我在企业知识库中暂时没找到相关的说明\"。"""
        return empty_prompt, []

    context = "\n---\n".join([doc["content"] for doc in docs])

    prompt = f"""
你是一个严谨的AI客服专员。请仅根据下面参考资料回答用户问题，禁止编造信息，如果参考资料中没有答案，请直接回答\"抱歉，我在企业知识库中暂时没找到相关的说明\"。

参考资料：
{context}

用户问题：{user_query}
"""
    return prompt, docs


def cosine_similarity_relevance(vec1: list, vec2: list) -> float:
    """计算两个向量的余弦相似度"""
    import numpy as np
    v1 = np.array(vec1, dtype=np.float32)
    v2 = np.array(vec2, dtype=np.float32)
    dot = np.dot(v1, v2)
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(dot / (norm1 * norm2))