import config
import os
from flask import Flask, redirect, url_for, session, request, render_template, flash
from database_create import SessionLocal, Prompt, User, Category
from sqlalchemy import select
import msal
import requests
from functools import wraps
import uuid

app = Flask(__name__)
app.config.from_object(config)
app.secret_key = os.getenv('SECRET_KEY', 'default-change-in-production')

def get_or_create_category(db, category_name):
    """Get category ID by name, create if doesn't exist"""
    category = db.query(Category).filter_by(name=category_name).first()
    if not category:
        category = Category(name=category_name)
        db.add(category)
        db.commit()
        db.refresh(category)
    return category.id

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

# 用 migrations 管理 schema，不需要 create_all()

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
        return redirect(url_for("home"))
    if "error" in request.args:
        flash(f"Login failed: {request.args['error_description']}", 'danger')
        return redirect(url_for("home"))

    app_msal = _build_msal_app()
    result = app_msal.acquire_token_by_authorization_code(
        request.args["code"],
        scopes=config.SCOPE or ["User.Read"],
        redirect_uri=config.REDIRECT_URI)

    if "access_token" in result:
        id_token_claims = result['id_token_claims']
        upn = id_token_claims.get('upn', id_token_claims.get('preferred_username'))
        oid = id_token_claims.get('oid')

        db = SessionLocal()
        try:
            user = db.query(User).filter_by(oid=oid).first()
            if not user:
                is_admin = upn in config.ADMINS
                user = User(oid=oid, upn=upn, is_admin=is_admin)
                db.add(user)
                db.commit()
                db.refresh(user)

            session["user"] = {"upn": upn, "oid": oid, "is_admin": user.is_admin}
            session["access_token"] = result.get("access_token")
            return redirect(url_for("home"))
        finally:
            db.close()

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
def home():
    query = request.args.get('query')
    selected_category = request.args.get('category', '所有分類')

    db = SessionLocal()
    try:
        categories = [c.name for c in db.query(Category).all()]
        prompts_query = db.query(Prompt).filter_by(is_approved=True)

        if selected_category and selected_category != '所有分類':
            category = db.query(Category).filter_by(name=selected_category).first()
            if category:
                prompts_query = prompts_query.filter_by(category_id=category.id)

        if query:
            search_term = f"%{query}%"
            prompts_query = prompts_query.filter(
                (Prompt.title.like(search_term)) | (Prompt.content.like(search_term))
            )

        approved_prompts = prompts_query.order_by(Prompt.id.desc()).all()

        return render_template("home.html",
                               prompts=approved_prompts,
                               categories=categories,
                               selected_category=selected_category,
                               current_query=query)
    finally:
        db.close()

@app.route("/share_prompt", methods=["GET", "POST"])
@login_required
def share_prompt():
    """讓使用者分享自己的 Prompt"""
    db = SessionLocal()
    try:
        categories = [c.name for c in db.query(Category).all()]

        if request.method == "POST":
            user = db.query(User).filter_by(oid=session['user']['oid']).first()
            if not user:
                flash("使用者資料錯誤。", 'danger')
                return redirect(url_for('home'))

            tags_input = request.form.get("tags", "")
            tags_list = [tag.strip() for tag in tags_input.split(',') if tag.strip()]

            category_id = get_or_create_category(db, request.form.get("category"))
            new_prompt = Prompt(
                title=request.form.get("title"),
                content=request.form.get("content"),
                category_id=category_id,
                description=request.form.get("description"),
                is_shared=True,
                is_approved=False,
                user_id=user.id
            )
            new_prompt.set_tags(tags_list)
            db.add(new_prompt)
            db.commit()
            return redirect(url_for("thank_you"))

        return render_template("share.html", categories=categories)
    finally:
        db.close()

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
    filter_status = request.args.get('status', 'all')

    db = SessionLocal()
    try:
        query = db.query(Prompt).filter_by(is_shared=True)

        if filter_status == 'approved':
            query = query.filter_by(is_approved=True)
        elif filter_status == 'pending':
            query = query.filter_by(is_approved=False)

        all_submitted_prompts = query.order_by(Prompt.is_approved.asc()).join(Category).all()

        return render_template("admin_review.html",
                               prompts=all_submitted_prompts,
                               filter_status=filter_status)
    finally:
        db.close()

@app.route("/admin/approve/<int:prompt_id>")
@admin_required
def approve_prompt(prompt_id):
    """審核並通過 Prompt (發布)"""
    db = SessionLocal()
    try:
        prompt = db.query(Prompt).filter_by(id=prompt_id).first()
        if not prompt:
            flash("Prompt not found.", 'danger')
            return redirect(url_for("admin_review"))
        if not prompt.is_approved:
            prompt.is_approved = True
            db.commit()
            flash(f"Prompt '{prompt.title}' 已成功通過審核，現在已公開。", 'success')
        return redirect(url_for("admin_review"))
    finally:
        db.close()


@app.route("/admin/unapprove/<int:prompt_id>")
@admin_required
def unapprove_prompt(prompt_id):
    """將已發布的 Prompt 下架 (unpublish)"""
    db = SessionLocal()
    try:
        prompt = db.query(Prompt).filter_by(id=prompt_id).first()
        if not prompt:
            flash("Prompt not found.", 'danger')
            return redirect(url_for("admin_review"))
        if prompt.is_approved:
            prompt.is_approved = False
            db.commit()
            flash(f"Prompt '{prompt.title}' 已成功下架 (取消發布)，現在為待審核狀態。", 'warning')
        else:
            flash(f"Prompt '{prompt.title}' 本來就未發布。", 'info')
        return redirect(url_for("admin_review"))
    finally:
        db.close()


@app.route("/admin/delete/<int:prompt_id>", methods=["POST"])
@admin_required
def admin_delete_prompt(prompt_id):
    """管理員刪除 Prompt"""
    db = SessionLocal()
    try:
        prompt = db.query(Prompt).filter_by(id=prompt_id).first()
        if not prompt:
            flash("Prompt not found.", 'danger')
            return redirect(url_for("admin_review"))
        title = prompt.title
        db.delete(prompt)
        db.commit()
        flash(f"Prompt '{title}' 已被管理員永久刪除。", 'danger')
        return redirect(url_for("admin_review"))
    finally:
        db.close()

@app.route("/admin/edit/<int:prompt_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_prompt(prompt_id):
    """管理員編輯 Prompt 內容和分類"""
    db = SessionLocal()
    try:
        categories = [c.name for c in db.query(Category).all()]
        prompt = db.query(Prompt).filter_by(id=prompt_id).first()
        if not prompt:
            flash("Prompt not found.", 'danger')
            return redirect(url_for("admin_review"))

        if request.method == "POST":
            prompt.title = request.form.get("title")
            prompt.content = request.form.get("content")
            prompt.category_id = get_or_create_category(db, request.form.get("category"))
            prompt.description = request.form.get("description")

            tags_input = request.form.get("tags", "")
            tags_list = [tag.strip() for tag in tags_input.split(',') if tag.strip()]
            prompt.set_tags(tags_list)

            db.commit()
            flash(f"Prompt '{prompt.title}' 已成功更新。", 'success')
            return redirect(url_for("admin_review"))

        return render_template("admin_edit.html",
                               prompt=prompt,
                               categories=categories,
                               is_admin=session['user']['is_admin'])
    finally:
        db.close()
# 省略其他路由...
@app.route("/admin/categories")
@admin_required
def admin_categories():
    """管理分類"""
    db = SessionLocal()
    try:
        categories = db.query(Category).all()
        return render_template("admin_categories.html", categories=categories)
    finally:
        db.close()

@app.route("/admin/add_category", methods=["POST"])
@admin_required
def admin_add_category():
    """新增分類"""
    db = SessionLocal()
    try:
        category_name = request.form.get("name", "").strip()
        if not category_name:
            flash("分類名稱不能為空。", 'warning')
            return redirect(url_for('admin_categories'))

        existing = db.query(Category).filter_by(name=category_name).first()
        if existing:
            flash(f"分類 '{category_name}' 已存在。", 'warning')
            return redirect(url_for('admin_categories'))

        new_category = Category(name=category_name)
        db.add(new_category)
        db.commit()
        flash(f"分類 '{category_name}' 已成功新增。", 'success')
        return redirect(url_for('admin_categories'))
    finally:
        db.close()

@app.route("/admin/edit_category/<int:category_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_category(category_id):
    """編輯分類"""
    db = SessionLocal()
    try:
        category = db.query(Category).filter_by(id=category_id).first()
        if not category:
            flash("分類不存在。", 'danger')
            return redirect(url_for('admin_categories'))

        if request.method == "POST":
            new_name = request.form.get("name", "").strip()
            if not new_name:
                flash("分類名稱不能為空。", 'warning')
                return redirect(url_for('admin_edit_category', category_id=category_id))

            existing = db.query(Category).filter_by(name=new_name).first()
            if existing and existing.id != category_id:
                flash(f"分類 '{new_name}' 已存在。", 'warning')
                return redirect(url_for('admin_edit_category', category_id=category_id))

            old_name = category.name
            category.name = new_name
            db.commit()
            flash(f"分類已成功更新：'{old_name}' → '{new_name}'。", 'success')
            return redirect(url_for('admin_categories'))

        return render_template("admin_edit_category.html", category=category)
    finally:
        db.close()

@app.route("/admin/delete_category/<int:category_id>", methods=["POST"])
@admin_required
def admin_delete_category(category_id):
    """刪除分類"""
    db = SessionLocal()
    try:
        category = db.query(Category).filter_by(id=category_id).first()
        if not category:
            flash("分類不存在。", 'danger')
            return redirect(url_for('admin_categories'))

        category_name = category.name
        db.delete(category)
        db.commit()
        flash(f"分類 '{category_name}' 已成功刪除。", 'success')
        return redirect(url_for('admin_categories'))
    except Exception as e:
        db.rollback()
        flash(f"刪除失敗，該分類可能仍有相關的 Prompt。", 'danger')
        return redirect(url_for('admin_categories'))
    finally:
        db.close()

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
    db = SessionLocal()
    try:
        prompt = db.query(Prompt).filter_by(id=prompt_id, is_approved=True).first()
        if not prompt:
            return {'error': 'Prompt not found'}, 404
        return {
            'id': prompt.id,
            'title': prompt.title,
            'category': prompt.category,
            'description': prompt.description,
            'tags': prompt.get_tags(),
            'content': prompt.content
        }
    finally:
        db.close()


@app.route("/api/search_by_intent", methods=["POST"])
def search_by_intent():
    """根據意圖搜尋相關 Prompts"""
    data = request.get_json()
    intent = data.get('intent', '').lower()

    if not intent:
        return {"error": "intent 不能為空"}, 400

    db = SessionLocal()
    try:
        approved_prompts = db.query(Prompt).filter_by(is_approved=True).all()

        results = []
        for prompt in approved_prompts:
            score = 0

            if intent in prompt.title.lower():
                score += 10

            if prompt.description and intent in prompt.description.lower():
                score += 5

            if prompt.tags:
                tags = prompt.get_tags()
                for tag in tags:
                    if intent in tag.lower():
                        score += 3

            if intent in prompt.content.lower():
                score += 1

            if score > 0:
                category_name = prompt.category.name if prompt.category else 'Unknown'
                results.append({
                    'id': prompt.id,
                    'title': prompt.title,
                    'category': category_name,
                    'description': prompt.description,
                    'tags': prompt.get_tags(),
                    'content': prompt.content,
                    'score': score
                })

        results.sort(key=lambda x: x['score'], reverse=True)

        return {
            'intent': intent,
            'results': results,
            'count': len(results)
        }
    finally:
        db.close()

if __name__ == '__main__':
    app.run(debug=True, port=5000)