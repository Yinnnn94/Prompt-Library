from fastmcp import FastMCP
import requests
import os 
from dotenv import load_dotenv


dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path)

mcp = FastMCP("Prompt Tool")
# Flask 應用的 API 地址
PROMPT_LIBRARY_API = os.getenv("PROMPT_LIBRARY_API", "http://localhost:5000")


@mcp.tool()
def search_prompts(intent: str) -> dict:
    """
    根據意圖搜尋 Prompt Library 中相關的 Prompts

    Args:
        intent: 搜尋意圖，例如「招聘」、「績效評估」、「程式碼審查」等

    Returns:
        包含匹配的 Prompts 列表，按相關度排序
    """
    try:
        payload = {"intent": intent}
        response = requests.post(f"{PROMPT_LIBRARY_API}/api/search_by_intent", json=payload, timeout=5)
        response.raise_for_status()

        result = response.json()
        return {
            "success": True,
            "intent": result.get("intent"),
            "count": result.get("count", 0),
            "results": result.get("results", [])
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": "無法連接到 Prompt Library 服務，請確保 Flask 應用運行在 http://localhost:5000"
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Prompt Library 服務請求超時"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"搜尋失敗: {str(e)}"
        }

@mcp.tool()
def get_prompt_content(prompt_id: int) -> dict:
    """
    獲取特定 Prompt 的完整內容
    Args:
        prompt_id: Prompt 的 ID（從 search_prompts 結果中取得）

    Returns:
        Prompt 的完整信息
    """
    try:
        response = requests.get(
            f"{PROMPT_LIBRARY_API}/api/prompt/{prompt_id}",
            timeout=5
        )
        if response.status_code == 404:
            return {
                "success": False,
                "error": f"找不到 ID 為 {prompt_id} 的 Prompt"
            }
        response.raise_for_status()
        return {
            "success": True,
            "prompt": response.json()
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": "無法連接到 Prompt Library 服務，請確保 Flask 應用運行在 http://localhost:5000"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"獲取 Prompt 失敗: {str(e)}"
        }
if __name__ == "__main__":
    mcp.run(transport="http", port=8003, host = "0.0.0.0")