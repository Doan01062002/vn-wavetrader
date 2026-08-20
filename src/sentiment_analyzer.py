import os
import re
import sys
import json
import logging
import requests
import pandas as pd
from vnstock import Reference

from src.llm_analyzer import init_gemini

# Khởi tạo logger
logger = logging.getLogger(__name__)

# Bộ từ điển tài chính tiếng Việt dùng để chấm điểm sắc thái dự phòng (Rule-based Fallback)
VIETNAMESE_BULLISH_KEYWORDS = [
    "tăng", "tăng trưởng", "kỷ lục", "bứt phá", "gom mua", "mua ròng", "vượt đỉnh",
    "lợi nhuận tăng", "tích cực", "khởi sắc", "tăng trần", "sóng tăng", "phục hồi",
    "mở rộng", "vượt kế hoạch", "trả cổ tức", "dòng tiền vào", "dẫn dắt", "bùng nổ",
    "hưởng lợi", "nâng hạng", "khởi công", "ký kết", "thắng thầu", "doanh thu tăng"
]

VIETNAMESE_BEARISH_KEYWORDS = [
    "giảm", "giảm mạnh", "bán tháo", "cắt lỗ", "thua lỗ", "giảm sàn", "tiêu cực",
    "suy thoái", "nợ xấu", "phạt", "cảnh báo", "bắt tạm giam", "hủy niêm yết",
    "bán ròng", "sụt giảm", "lao dốc", "khủng hoảng", "thanh tra", "sai phạm",
    "đình chỉ", "khó khăn", "vỡ nợ", "áp lực bán", "thủng đáy", "thua lỗ kỷ lục"
]


def _score_text_with_keywords(text: str) -> float:
    """
    Tính điểm sắc thái của chuỗi văn bản dựa trên từ điển ngữ nghĩa tiếng Việt.
    Trả về điểm từ -1.0 đến +1.0.
    """
    text_lower = text.lower()
    bull_count = sum(1 for kw in VIETNAMESE_BULLISH_KEYWORDS if kw in text_lower)
    bear_count = sum(1 for kw in VIETNAMESE_BEARISH_KEYWORDS if kw in text_lower)

    if bull_count == 0 and bear_count == 0:
        return 0.0
    
    total = bull_count + bear_count
    score = (bull_count - bear_count) / total
    return max(-1.0, min(1.0, round(score, 2)))


def fetch_cafef_rss_news() -> list:
    """
    Cào các tin tức chứng khoán mới nhất từ RSS feed Kinh doanh của VnExpress và Cafef.
    Sử dụng đa nguồn để đảm bảo luôn có dữ liệu.
    """
    sources = [
        {"name": "VnExpress", "url": "https://vnexpress.net/rss/kinh-doanh.rss"},
        {"name": "Cafef", "url": "https://cafef.vn/thi-truong-chung-khoan.rss"}
    ]
    
    news_list = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for src in sources:
        try:
            logger.info(f"Đang cào dữ liệu RSS tin tức từ {src['name']}...")
            r = requests.get(src["url"], headers=headers, timeout=10)
            if r.status_code != 200:
                logger.warning(f"Không thể cào RSS {src['name']}, mã lỗi: {r.status_code}")
                continue

            xml_text = r.text
            items = re.findall(r'<item>(.*?)</item>', xml_text, re.DOTALL)

            for item in items[:10]:
                title_match = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', item) or re.search(r'<title>(.*?)</title>', item)
                title = title_match.group(1).strip() if title_match else ""

                link_match = re.search(r'<link><!\[CDATA\[(.*?)\]\]></link>', item) or re.search(r'<link>(.*?)</link>', item)
                link = link_match.group(1).strip() if link_match else ""

                pub_date_match = re.search(r'<pubDate><!\[CDATA\[(.*?)\]\]></pubDate>', item) or re.search(r'<pubDate>(.*?)</pubDate>', item)
                pub_date = pub_date_match.group(1).strip() if pub_date_match else ""

                title = re.sub(r'<!\[CDATA\[|\]\]>', '', title).strip()
                link = re.sub(r'<!\[CDATA\[|\]\]>', '', link).strip()

                if title and not any(n["title"] == title for n in news_list):
                    news_list.append({
                        "title": title,
                        "url": link,
                        "time": pub_date,
                        "source": src["name"]
                    })
        except Exception as e:
            logger.warning(f"Lỗi khi cào RSS {src['name']}: {e}")

    logger.info(f"Tổng hợp thành công {len(news_list)} tin tức thị trường từ các nguồn RSS.")
    return news_list[:15]


def _extract_json_from_llm_response(text: str):
    """Trích xuất và parse danh sách JSON an toàn từ phản hồi của LLM."""
    if not text:
        return None
        
    text_clean = text.strip()
    
    # 1. Thử bóc tách từ khối markdown code block ```json ... ```
    code_block = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text_clean)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except Exception:
            pass

    # 2. Thử tìm khối mảng JSON [ ... ]
    array_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', text_clean)
    if array_match:
        try:
            return json.loads(array_match.group(0).strip())
        except Exception:
            pass

    # 3. Thử parse trực tiếp chuỗi đã làm sạch
    try:
        return json.loads(text_clean)
    except Exception:
        pass

    # 4. Fallback: Parse regex từng item {"index": 1, "score": 0.5, ...}
    items = []
    for m in re.finditer(r'\{\s*"index"\s*:\s*(\d+)\s*,\s*"score"\s*:\s*([-+]?\d*\.?\d+)(?:,\s*"sentiment"\s*:\s*"([^"]*)")?\s*\}', text_clean):
        idx = int(m.group(1))
        sc = float(m.group(2))
        sent = m.group(3) or ("Tích cực" if sc > 0.1 else ("Tiêu cực" if sc < -0.1 else "Trung tính"))
        items.append({"index": idx, "score": sc, "sentiment": sent})

    return items if items else None


def _build_rule_based_sentiment(news_list: list) -> dict:
    """Tạo đánh giá sắc thái dựa trên từ khóa tài chính khi AI không khả dụng hoặc lỗi."""
    details = []
    total_score = 0.0
    pos_count = 0
    neg_count = 0
    neutral_count = 0

    for n in news_list:
        score = _score_text_with_keywords(n["title"])
        if score >= 0.15:
            sentiment = "Tích cực"
            pos_count += 1
        elif score <= -0.15:
            sentiment = "Tiêu cực"
            neg_count += 1
        else:
            sentiment = "Trung tính"
            neutral_count += 1

        details.append({
            "title": n["title"],
            "url": n.get("url", ""),
            "time": n.get("time", ""),
            "score": score,
            "sentiment": sentiment
        })
        total_score += score

    num_items = len(details)
    avg_score = total_score / num_items if num_items > 0 else 0.0
    bullish_pct = (pos_count / num_items * 100) if num_items > 0 else 50.0
    bearish_pct = (neg_count / num_items * 100) if num_items > 0 else 50.0

    if avg_score >= 0.35:
        market_label = "HƯNG PHẤN (Greed)"
    elif avg_score >= 0.1:
        market_label = "LẠC QUAN (Slight Greed)"
    elif avg_score <= -0.35:
        market_label = "HOẢNG LOẠN (Fear)"
    elif avg_score <= -0.1:
        market_label = "BI QUAN (Slight Fear)"
    else:
        market_label = "TRUNG TÍNH (Neutral)"

    analysis_text = f"Tâm lý thị trường ghi nhận {market_label} với điểm sắc thái {avg_score:+.2f}. " \
                    f"Tỷ lệ tin tích cực: {bullish_pct:.0f}%, tiêu cực: {bearish_pct:.0f}%."

    return {
        "score": avg_score,
        "label": market_label,
        "bullish_pct": bullish_pct,
        "bearish_pct": bearish_pct,
        "details": details,
        "sentiment_score": f"{market_label} ({avg_score:+.2f})",
        "analysis": analysis_text
    }


def evaluate_sentiment_with_ai(news_list: list) -> dict:
    """
    Sử dụng Groq AI để phân tích sắc thái hàng loạt tin tức cùng lúc.
    Tự động chuyển đổi sang Rule-based Fallback nếu AI lỗi hoặc không có API key.
    """
    if not news_list:
        return {
            "score": 0.0,
            "label": "TRUNG TÍNH (Neutral)",
            "bullish_pct": 50.0,
            "bearish_pct": 50.0,
            "details": [],
            "sentiment_score": "TRUNG TÍNH (Neutral) (+0.00)",
            "analysis": "Không có tin tức mới ghi nhận trong phiên."
        }

    model = init_gemini()
    if not model:
        logger.info("Không có Groq AI client, sử dụng bộ chấm điểm quy tắc từ khóa tiếng Việt.")
        return _build_rule_based_sentiment(news_list)

    titles_str = "\n".join([f"{i+1}. {n['title']}" for i, n in enumerate(news_list)])

    prompt = f"""Bạn là chuyên gia phân tích tâm lý thị trường chứng khoán Việt Nam.
Hãy đánh giá sắc thái (sentiment) của danh sách các tiêu đề tin tức sau đây:
{titles_str}

Hãy trả về DUY NHẤT một danh sách JSON hợp lệ. Với mỗi tin tức, hãy gán điểm sắc thái (score) từ -1.0 (rất tiêu cực/xấu) đến +1.0 (rất tích cực/tốt). Tin trung tính gán 0.0.
Cấu trúc JSON yêu cầu chính xác:
[
  {{"index": 1, "score": 0.5, "sentiment": "Tích cực"}},
  {{"index": 2, "score": -0.8, "sentiment": "Tiêu cực"}}
]
"""
    try:
        response = model.generate_content(prompt)
        scores_list = None
        if response and hasattr(response, 'text'):
            scores_list = _extract_json_from_llm_response(response.text)

        if not scores_list:
            logger.warning("Không trích xuất được JSON từ phản hồi AI, chuyển sang phân tích từ khóa.")
            return _build_rule_based_sentiment(news_list)

        details = []
        total_score = 0.0
        pos_count = 0
        neg_count = 0
        neutral_count = 0

        for item in scores_list:
            idx = item.get("index", 1) - 1
            if 0 <= idx < len(news_list):
                score = float(item.get("score", 0.0))
                label = item.get("sentiment", "Trung tính")

                details.append({
                    "title": news_list[idx]["title"],
                    "url": news_list[idx].get("url", ""),
                    "time": news_list[idx].get("time", ""),
                    "score": score,
                    "sentiment": label
                })

                total_score += score
                if score >= 0.15:
                    pos_count += 1
                elif score <= -0.15:
                    neg_count += 1
                else:
                    neutral_count += 1

        num_items = len(details)
        avg_score = total_score / num_items if num_items > 0 else 0.0
        bullish_pct = (pos_count / num_items * 100) if num_items > 0 else 50.0
        bearish_pct = (neg_count / num_items * 100) if num_items > 0 else 50.0

        if avg_score >= 0.4:
            market_label = "HƯNG PHẤN TỘT ĐỘ (Extreme Greed)"
        elif avg_score >= 0.15:
            market_label = "LẠC QUAN (Greed)"
        elif avg_score <= -0.4:
            market_label = "HOẢNG LOẠN TỘT ĐỘ (Extreme Fear)"
        elif avg_score <= -0.15:
            market_label = "BI QUAN (Fear)"
        else:
            market_label = "TRUNG TÍNH (Neutral)"

        analysis_text = f"Tâm lý thị trường chung: {market_label} (Điểm: {avg_score:+.2f}). " \
                        f"Tỷ lệ tin tích cực: {bullish_pct:.0f}%, tin tiêu cực: {bearish_pct:.0f}%."

        return {
            "score": avg_score,
            "label": market_label,
            "bullish_pct": bullish_pct,
            "bearish_pct": bearish_pct,
            "details": details,
            "sentiment_score": f"{market_label} ({avg_score:+.2f})",
            "analysis": analysis_text
        }

    except Exception as e:
        logger.warning(f"Lỗi khi Groq phân tích tâm lý: {e}. Chuyển sang phân tích từ khóa.")
        return _build_rule_based_sentiment(news_list)


def analyze_market_sentiment() -> dict:
    """Quét và đo lường tâm lý chung của toàn bộ thị trường dựa trên tin tức RSS."""
    news = fetch_cafef_rss_news()
    return evaluate_sentiment_with_ai(news)


def analyze_stock_sentiment(symbol: str) -> dict:
    """Quét và đo lường tâm lý riêng của một mã cổ phiếu dựa trên tin tức doanh nghiệp vnstock."""
    try:
        logger.info(f"Đang lấy tin tức từ vnstock cho mã {symbol}...")
        ref = Reference()
        df_news = ref.company(symbol).news()

        if df_news is None or df_news.empty or "title" not in df_news.columns:
            return {
                "score": 0.0,
                "label": "TRUNG TÍNH (Neutral)",
                "bullish_pct": 50.0,
                "bearish_pct": 50.0,
                "details": [],
                "sentiment_score": "TRUNG TÍNH (Neutral) (+0.00)",
                "analysis": f"Không có tin tức mới cho mã {symbol}."
            }

        news_list = []
        for _, row in df_news.head(10).iterrows():
            news_list.append({
                "title": row["title"],
                "url": row.get("url", ""),
                "time": row.get("publish_time", "")
            })

        return evaluate_sentiment_with_ai(news_list)
    except Exception as e:
        logger.warning(f"Lỗi khi lấy tin tức cho mã {symbol}: {e}")
        return {
            "score": 0.0,
            "label": "TRUNG TÍNH (Neutral)",
            "bullish_pct": 50.0,
            "bearish_pct": 50.0,
            "details": [],
            "sentiment_score": "TRUNG TÍNH (Neutral) (+0.00)",
            "analysis": f"Không tải được tin tức cho mã {symbol}."
        }

