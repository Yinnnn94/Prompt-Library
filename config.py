import os
import dotenv

dotenv.load_dotenv(dotenv_path=".env", override=True)
# 從 Azure Portal 取得
CLIENT_ID = os.getenv("AAD_CLIENT_ID", "YOUR_CLIENT_ID")
CLIENT_SECRET = os.getenv("AAD_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
TENANT_ID = os.getenv("AAD_TENANT_ID", "YOUR_TENANT_ID")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_PATH = "/auth/callback"  # 必須與 Azure Portal 中設定的 Redirect URI 路徑一致
ENDPOINT = 'https://graph.microsoft.com/v1.0/users' # Graph API endpoint
SCOPE = ['User.Read']  # 需要的權限範圍

# 管理員電子郵件/UPN 列表 (硬編碼範例，實際應用中可存在資料庫)
ADMINS = ['admin@example.com']
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:5000/auth/callback")  # 必須與 Azure Portal 中設定的 Redirect URI 一致


# 資料庫配置
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "prompt_library")
SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@db:{DB_PORT}/{DB_NAME}"
SQLALCHEMY_TRACK_MODIFICATIONS = False