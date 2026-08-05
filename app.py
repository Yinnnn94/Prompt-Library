import config
from flask import Flask, redirect, url_for, session, request, render_template, flash
from prompt_library.database_createse import db, Prompt, User
import msal
import requests
from functools import wraps
import uuid

app = Flask(__name__)
app.config.from_object(config)
app.secret_key = 'super_secret_key' # 在實際應用中請使用更安全的密鑰
db.init_app(app)

CATEGORY_COLORS = {
    'HR': 'info',       # 藍色
    'RD': 'primary',    # 深藍色
    '通用型': 'success', # 綠色
    '行銷': 'danger',    # 紅色
    '其他': 'secondary' # 灰色
}

# 將顏色對應字典傳遞給所有模板
@app.context_processor
def utility_processor():
    def get_category_color(category):
        return CATEGORY_COLORS.get(category, 'light') # 默認為淺色
    return dict(get_category_color=get_category_color)

with app.app_context():
    db.create_all()

# -----------------
# 🎯 AAD 身份驗證路由
# -----------------

def _build_msal_app(cache=None, **kwargs):
    """建立 MSAL 實例"""
    return msal.ConfidentialClientApplication(
        config.CLIENT_ID, authority=config.AUTHORITY,
        client_credential=config.CLIENT_SECRET, token_cache=cache, **kwargs)

@app.route("/login")
def login():
    """導向 AAD 登入頁面"""
    session["state"] = str(uuid.uuid4())
    app_msal = _build_msal_app()
    auth_url = app_msal.get_authorization_request_url(
        config.SCOPE or ["User.Read"],
        state=session["state"],
        redirect_uri=config.REDIRECT_URI
    )
    return redirect(auth_url)

@app.route(config.REDIRECT_PATH)
def auth_callback():
    """處理 AAD 登入回呼"""
    if request.args.get('state') != session.get("state"):
        return redirect(url_for("home")) # 狀態碼不匹配，拒絕
    if "error" in request.args:
        flash(f"Login failed: {request.args['error_description']}", 'danger')
        return redirect(url_for("home"))

    app_msal = _build_msal_app()
    result = app_msal.acquire_token_by_authorization_code(
        request.args["code"],
        scopes=config.SCOPE or ["User.Read"],
        redirect_uri=config.REDIRECT_URI)

    if "access_token" in result:
        # 取得使用者資料 (ID Token 包含基本資訊)
        id_token_claims = result['id_token_claims']
        upn = id_token_claims.get('upn', id_token_claims.get('preferred_username'))
        oid = id_token_claims.get('oid')

        # 檢查或創建使用者
        user = User.query.filter_by(oid=oid).first()
        if not user:
            # 設定管理員權限
            is_admin = upn in config.ADMINS
            user = User(oid=oid, upn=upn, is_admin=is_admin)
            db.session.add(user)
            db.session.commit()
            
        session["user"] = {"upn": upn, "oid": oid, "is_admin": user.is_admin}
        session["access_token"] = result.get("access_token")
        
        return redirect(url_for("home"))
    
    flash("AAD Authentication failed.", 'danger')
    return redirect(url_for("home"))

@app.route("/logout")
def logout():
    """登出"""
    session.clear()
    return redirect(url_for("home"))

# -----------------
# 💻 Prompt Hub 路由
# -----------------

def login_required(f):
    """檢查使用者是否登入的裝飾器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash("請先登入。", 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
@app.route("/")
def home():
    # 獲取 URL 參數
    query = request.args.get('query')
    selected_category = request.args.get('category', '所有分類')
    categories = ['HR', 'RD', '通用型', '行銷', '其他']
    
    # 基礎查詢：只顯示已發布的
    prompts_query = Prompt.query.filter_by(is_approved=True)
    
    # 1. 分類篩選邏輯
    if selected_category and selected_category != '所有分類':
        prompts_query = prompts_query.filter_by(category=selected_category)
    
    # 2. 搜尋關鍵字邏輯
    if query:
        search_term = f"%{query}%"
        prompts_query = prompts_query.filter(
            (Prompt.title.like(search_term)) | (Prompt.content.like(search_term))
        )
    
    # 執行查詢 (按 ID 倒序排列，最新的在前)
    approved_prompts = prompts_query.order_by(Prompt.id.desc()).all()
    
    return render_template("home.html", 
                           prompts=approved_prompts, 
                           categories=categories,
                           selected_category=selected_category,
                           current_query=query)

@app.route("/share_prompt", methods=["GET", "POST"])
@login_required
def share_prompt():
    """讓使用者分享自己的 Prompt"""
    categories = ['HR', 'RD', '通用型', '行銷', '其他']
    
    if request.method == "POST":
        user = User.query.filter_by(oid=session['user']['oid']).first()
        if not user:
            flash("使用者資料錯誤。", 'danger')
            return redirect(url_for('home'))

        tags_input = request.form.get("tags", "")
        tags_list = [tag.strip() for tag in tags_input.split(',') if tag.strip()]

        new_prompt = Prompt(
            title=request.form.get("title"),
            content=request.form.get("content"),
            category=request.form.get("category"),
            description=request.form.get("description"),
            is_shared=True,
            is_approved=False,
            user_id=user.id
        )
        new_prompt.set_tags(tags_list)
        db.session.add(new_prompt)
        db.session.commit()
        return redirect(url_for("thank_you"))
    
    # 傳遞分類列表給 share.html
    return render_template("share.html", categories=categories)

# -----------------
# 🛡️ 管理員審核路由
# -----------------

def admin_required(f):
    """檢查是否為管理員的裝飾器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session or not session['user'].get('is_admin'):
            flash("您沒有管理員權限！", 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/admin/review")
@admin_required
def admin_review():
    """顯示所有已提交的 Prompts，並支持按狀態篩選"""
    
    # 獲取 URL 查詢參數中的 'status'
    # 'all': 全部, 'approved': 已發佈, 'pending': 待審核
    filter_status = request.args.get('status', 'all')
    
    # 基礎查詢：只查詢已分享/提交的 Prompts
    query = Prompt.query.filter_by(is_shared=True)

    if filter_status == 'approved':
        # 篩選已發佈的
        query = query.filter_by(is_approved=True)
    elif filter_status == 'pending':
        # 篩選待審核的
        query = query.filter_by(is_approved=False)
    
    # 排序：優先顯示未審核的 (如果 filter_status='all')
    all_submitted_prompts = query.order_by(Prompt.is_approved.asc()).all()
    
    # 傳遞給模板
    return render_template("admin_review.html", 
                           prompts=all_submitted_prompts, 
                           filter_status=filter_status
                          )

@app.route("/admin/approve/<int:prompt_id>")
@admin_required
def approve_prompt(prompt_id):
    """審核並通過 Prompt (發布)"""
    prompt = Prompt.query.get_or_404(prompt_id)
    if not prompt.is_approved:
        prompt.is_approved = True
        db.session.commit()
        flash(f"Prompt '{prompt.title}' 已成功通過審核，現在已公開。", 'success')
    return redirect(url_for("admin_review"))


@app.route("/admin/unapprove/<int:prompt_id>")
@admin_required
def unapprove_prompt(prompt_id):
    """將已發布的 Prompt 下架 (unpublish)"""
    prompt = Prompt.query.get_or_404(prompt_id)
    if prompt.is_approved:
        # 將狀態設回 False，使其不再顯示在主頁
        prompt.is_approved = False
        db.session.commit()
        flash(f"Prompt '{prompt.title}' 已成功下架 (取消發布)，現在為待審核狀態。", 'warning')
    else:
        flash(f"Prompt '{prompt.title}' 本來就未發布。", 'info')
        
    return redirect(url_for("admin_review"))


@app.route("/admin/delete/<int:prompt_id>", methods=["POST"])
@admin_required
def admin_delete_prompt(prompt_id):
    """管理員刪除 Prompt"""
    prompt = Prompt.query.get_or_404(prompt_id)
    title = prompt.title
    
    # 執行刪除操作
    db.session.delete(prompt)
    db.session.commit()
    
    flash(f"Prompt '{title}' 已被管理員永久刪除。", 'danger')
    
    # 刪除後導回審核頁面
    return redirect(url_for("admin_review"))

@app.route("/admin/edit/<int:prompt_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_prompt(prompt_id):
    """管理員編輯 Prompt 內容和分類"""
    prompt = Prompt.query.get_or_404(prompt_id)
    categories = ['HR', 'RD', '通用型', '行銷', '其他']

    if request.method == "POST":
        prompt.title = request.form.get("title")
        prompt.content = request.form.get("content")
        prompt.category = request.form.get("category")
        prompt.description = request.form.get("description")

        tags_input = request.form.get("tags", "")
        tags_list = [tag.strip() for tag in tags_input.split(',') if tag.strip()]
        prompt.set_tags(tags_list)

        db.session.commit()
        flash(f"Prompt '{prompt.title}' 已成功更新。", 'success')
        return redirect(url_for("admin_review"))

    # GET 請求：顯示編輯表單
    return render_template("admin_edit.html", 
                           prompt=prompt, 
                           categories=categories, 
                           is_admin=session['user']['is_admin'])
# 省略其他路由...
@app.route("/thank_you")
def thank_you():
    """新的感謝頁面路由"""
    return render_template("thank_you.html")

# -----------------
# 🔍 智能搜尋 API (用於 MCP 工具)
# -----------------

@app.route("/api/prompt/<int:prompt_id>", methods=["GET"])
def get_prompt(prompt_id):
    """根據 ID 獲取單一 Prompt 的完整內容"""
    prompt = Prompt.query.filter_by(id=prompt_id, is_approved=True).first_or_404()
    return {
        'id': prompt.id,
        'title': prompt.title,
        'category': prompt.category,
        'description': prompt.description,
        'tags': prompt.get_tags(),
        'content': prompt.content
    }

@app.route("/api/search_by_intent", methods=["POST"])
def search_by_intent():
    """根據意圖搜尋相關 Prompts"""
    data = request.get_json()
    intent = data.get('intent', '').lower()

    if not intent:
        return {"error": "intent 不能為空"}, 400

    approved_prompts = Prompt.query.filter_by(is_approved=True).all()

    results = []
    for prompt in approved_prompts:
        score = 0

        # 標題匹配 (權重最高)
        if intent in prompt.title.lower():
            score += 10

        # 描述匹配
        if prompt.description and intent in prompt.description.lower():
            score += 5

        # 標籤匹配
        if prompt.tags:
            tags = prompt.get_tags()
            for tag in tags:
                if intent in tag.lower():
                    score += 3

        # 內容匹配
        if intent in prompt.content.lower():
            score += 1

        if score > 0:
            results.append({
                'id': prompt.id,
                'title': prompt.title,
                'category': prompt.category,
                'description': prompt.description,
                'tags': prompt.get_tags(),
                'content': prompt.content,
                'score': score
            })

    # 按相關度排序
    results.sort(key=lambda x: x['score'], reverse=True)

    return {
        'intent': intent,
        'results': results,
        'count': len(results)
    }

if __name__ == '__main__':
    app.run(debug=True, port=5000)