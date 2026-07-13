import os
import re
import sys
import json
import logging
import requests
import pandas as pd
from vnstock import Reference

# Add project root to path
sys.path.append(os.getcwd())

from src.llm_analyzer import init_gemini

# Khởi tạo logger
logger = logging.getLogger(__name__)

def fetch_cafef_rss_news() -> list:
    """
    Cào các tin tức chứng khoán mới nhất từ RSS feed Kinh doanh của VnExpress.
    Sử dụng Regex để parse để tránh lỗi cú pháp XML thực tế.
    """
    url = "https://vnexpress.net/rss/kinh-doanh.rss"
    try:
        logger.info("Đang cào dữ liệu RSS tin tức thị trường từ VnExpress...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            logger.error(f"Không thể cào VnExpress RSS, mã lỗi: {r.status_code}")
            return []
            
        xml_text = r.text
        # Tìm tất cả thẻ <item>
        items = re.findall(r'<item>(.*?)</item>', xml_text, re.DOTALL)
        news_list = []
        
        for item in items[:15]: # Lấy tối đa 15 tin tức gần nhất
            # Lấy Title
            title_match = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', item)
            if not title_match:
                title_match = re.search(r'<title>(.*?)</title>', item)
            title = title_match.group(1).strip() if title_match else ""
            
            # Lấy Link
            link_match = re.search(r'<link><!\[CDATA\[(.*?)\]\]></link>', item)
            if not link_match:
                link_match = re.search(r'<link>(.*?)</link>', item)
            link = link_match.group(1).strip() if link_match else ""
            
            # Lấy PubDate
            pub_date_match = re.search(r'<pubDate><!\[CDATA\[(.*?)\]\]></pubDate>', item)
            if not pub_date_match:
                pub_date_match = re.search(r'<pubDate>(.*?)</pubDate>', item)
            pub_date = pub_date_match.group(1).strip() if pub_date_match else ""
            
            # Làm gọn title nếu chứa các CDATA thừa
            title = re.sub(r'<!\[CDATA\[|\]\]>', '', title)
            link = re.sub(r'<!\[CDATA\[|\]\]>', '', link)
            
            if title:
                news_list.append({
                    "title": title,
                    "url": link,
                    "time": pub_date
                })
        logger.info(f"Cào thành công {len(news_list)} tin tức thị trường từ VnExpress.")
        return news_list
    except Exception as e:
        logger.error(f"Lỗi khi cào RSS VnExpress: {e}")
        return []

def evaluate_sentiment_with_ai(news_list: list) -> dict:
    """
    Sử dụng Gemini AI để phân tích sắc thái hàng loạt tin tức cùng lúc để tiết kiệm request.
    Trả về cấu trúc tổng hợp chỉ số tâm lý.
    """
    if not news_list:
        return {
            "score": 0.0,
            "label": "TRUNG TÍNH (Neutral)",
            "bullish_pct": 50.0,
            "bearish_pct": 50.0,
            "details": []
        }
        
    model = init_gemini()
    if not model:
        logger.warning("Không khởi tạo được Groq AI, sử dụng đánh giá trung tính mặc định.")
        return {
            "score": 0.0,
            "label": "TRUNG TÍNH (Neutral)",
            "bullish_pct": 50.0,
            "bearish_pct": 50.0,
            "details": [{"title": n["title"], "score": 0.0, "sentiment": "Trung tính"} for n in news_list]
        }
        
    # Tạo chuỗi danh sách tiêu đề gửi cho AI
    titles_str = "\n".join([f"{i+1}. {n['title']}" for i, n in enumerate(news_list)])
    
    prompt = f"""
Bạn là một chuyên gia phân tích tâm lý đám đông trên thị trường chứng khoán Việt Nam.
Hãy đánh giá sắc thái (sentiment) của danh sách các tiêu đề tin tức tài chính sau đây:
{titles_str}

Hãy trả về một danh sách JSON duy nhất. Với mỗi tin tức, hãy gán điểm số sắc thái (score) nằm trong khoảng từ -1.0 (Cực kỳ tiêu cực, hoảng loạn, tin xấu) đến +1.0 (Cực kỳ tích cực, hưng phấn, tin tốt). Tin trung tính gán giá trị 0.0.
Cấu trúc JSON yêu cầu trả về chính xác như sau (không kèm mã markdown ```json hay văn bản giải thích nào khác):
[
  {{"index": 1, "score": 0.5, "sentiment": "Tích cực"}},
  {{"index": 2, "score": -0.8, "sentiment": "Tiêu cực"}},
  ...
]
"""
    try:
        response = model.generate_content(prompt)
        # Làm sạch chuỗi phản hồi phòng hờ AI tự bọc khối ```json
        response_text = response.text.strip()
        response_text = re.sub(r"^```json\s*|```$", "", response_text, flags=re.MULTILINE).strip()
        
        scores_list = json.loads(response_text)
        
        # Áp điểm số vào danh sách gốc
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
        
        # Tính phần trăm
        bullish_pct = (pos_count / num_items * 100) if num_items > 0 else 50.0
        bearish_pct = (neg_count / num_items * 100) if num_items > 0 else 50.0
        
        # Định nghĩa nhãn trạng thái tổng hợp
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
            
        return {
            "score": avg_score,
            "label": market_label,
            "bullish_pct": bullish_pct,
            "bearish_pct": bearish_pct,
            "details": details
        }
        
    except Exception as e:
        logger.error(f"Lỗi khi Groq phân tích tâm lý tin tức: {e}")
        # Trả về kết quả trung tính nếu lỗi
        return {
            "score": 0.0,
            "label": "TRUNG TÍNH (Lỗi phân tích)",
            "bullish_pct": 50.0,
            "bearish_pct": 50.0,
            "details": [{"title": n["title"], "score": 0.0, "sentiment": "Trung tính"} for n in news_list]
        }

def analyze_market_sentiment() -> dict:
    """
    Quét và đo lường tâm lý chung của toàn bộ thị trường dựa trên tin tức Cafef.
    """
    news = fetch_cafef_rss_news()
    return evaluate_sentiment_with_ai(news)

def analyze_stock_sentiment(symbol: str) -> dict:
    """
    Quét và đo lường tâm lý riêng của một mã cổ phiếu dựa trên tin tức doanh nghiệp của vnstock.
    """
    try:
        logger.info(f"Đang lấy tin tức từ vnstock cho mã {symbol}...")
        ref = Reference()
        df_news = ref.company(symbol).news()
        
        if df_news.empty or "title" not in df_news.columns:
            return {
                "score": 0.0,
                "label": "TRUNG TÍNH (Không có tin tức)",
                "bullish_pct": 50.0,
                "bearish_pct": 50.0,
                "details": []
            }
            
        # Lấy tối đa 10 tin tức gần nhất
        news_list = []
        for _, row in df_news.head(10).iterrows():
            news_list.append({
                "title": row["title"],
                "url": row.get("url", ""),
                "time": row.get("publish_time", "")
            })
            
        return evaluate_sentiment_with_ai(news_list)
    except Exception as e:
        logger.error(f"Lỗi khi phân tích tâm lý mã {symbol}: {e}")
        return {
            "score": 0.0,
            "label": f"TRUNG TÍNH (Lỗi: {e})",
            "bullish_pct": 50.0,
            "bearish_pct": 50.0,
            "details": []
        }
