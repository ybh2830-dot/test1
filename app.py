"""쇼핑 리스트 앱 (Streamlit + SQLite)"""
import html
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
SAMPLE_NAMES = [("우유", 2), ("계란", 1), ("두부", 1)]
MAX_NAME_LEN = 50
MIN_QTY, MAX_QTY = 1, 99
# 디자인 색상 (라이트/다크 모두에서 읽히도록 투명도를 쓴다)
ACCENT = "#2E7D32"
ACCENT_HOVER = "#388E3C"
ACCENT_SOFT = "rgba(46, 125, 50, 0.16)"
LINE = "rgba(128, 128, 128, 0.25)"
DB_PATH = Path(os.environ.get("SHOPPING_DB", Path(__file__).with_name("shopping.db")))


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 저장소 (SQLite). UI는 아래 함수만 사용하므로 저장소를 바꿔도 UI는 그대로다.
# ---------------------------------------------------------------------------
@contextmanager
def db():
    """트랜잭션으로 묶고, 끝나면 연결을 닫는다."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    """테이블이 없을 때만 만들고, 처음 만든 경우에만 예시 항목을 넣는다."""
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")  # 동시에 첫 접속해도 한 곳에서만 생성한다
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='items'"
        ).fetchone()
        if exists:
            return
        conn.execute(
            """CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                checked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )"""
        )
        conn.executemany(
            "INSERT INTO items (name, quantity, created_at) VALUES (?, ?, ?)",
            [(name, qty, now_iso()) for name, qty in SAMPLE_NAMES],
        )


def list_items() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
    return [{**dict(r), "checked": bool(r["checked"])} for r in rows]


def find_item(item_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return {**dict(row), "checked": bool(row["checked"])} if row else None


def add_item(name: str, quantity: int = 1) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO items (name, quantity, created_at) VALUES (?, ?, ?)",
            (name, quantity, now_iso()),
        )


def update_item(item_id: int, name: str, quantity: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE items SET name = ?, quantity = ? WHERE id = ?", (name, quantity, item_id)
        )


def delete_item(item_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))


def toggle_item(item_id: int) -> None:
    with db() as conn:
        conn.execute("UPDATE items SET checked = 1 - checked WHERE id = ?", (item_id,))


def clear_checked() -> None:
    with db() as conn:
        conn.execute("DELETE FROM items WHERE checked = 1")


def init_state() -> None:
    """화면 상태(수정 중인 항목, 안내 메시지)만 세션에 둔다. 항목 데이터는 DB에 있다."""
    init_db()
    st.session_state.setdefault("editing_id", None)
    st.session_state.setdefault("flash", None)


# ---------------------------------------------------------------------------
# 검증과 콜백
# ---------------------------------------------------------------------------
def validate_name(raw: str) -> tuple[str, str | None]:
    """공백을 제거한 이름과 오류 메시지(없으면 None)를 돌려준다."""
    name = (raw or "").strip()
    if not name:
        return name, "물건 이름을 입력해 주세요."
    if len(name) > MAX_NAME_LEN:
        return name, f"이름은 {MAX_NAME_LEN}자 이하로 입력해 주세요. (현재 {len(name)}자)"
    return name, None


def validate_qty(raw) -> tuple[int, str | None]:
    """수량과 오류 메시지(없으면 None)를 돌려준다."""
    message = f"수량은 {MIN_QTY}~{MAX_QTY} 사이의 숫자로 입력해 주세요."
    try:
        qty = int(raw)
    except (TypeError, ValueError):
        return MIN_QTY, message
    if not MIN_QTY <= qty <= MAX_QTY:
        return qty, message
    return qty, None


def validate_input(raw_name, raw_qty) -> tuple[str, int, str | None]:
    name, error = validate_name(raw_name)
    qty, qty_error = validate_qty(raw_qty)
    return name, qty, error or qty_error


def on_add() -> None:
    name, qty, error = validate_input(
        st.session_state.get("new_name", ""), st.session_state.get("new_qty")
    )
    if error:
        st.session_state.flash = error
        return
    add_item(name, qty)


def on_start_edit(item_id: int) -> None:
    item = find_item(item_id)
    if item is None:
        return
    # 수정 모드는 한 번에 한 항목만 허용한다.
    st.session_state.editing_id = item_id
    st.session_state[f"edit_name_{item_id}"] = item["name"]
    st.session_state[f"edit_qty_{item_id}"] = item["quantity"]


def on_save_edit(item_id: int) -> None:
    name, qty, error = validate_input(
        st.session_state.get(f"edit_name_{item_id}", ""),
        st.session_state.get(f"edit_qty_{item_id}"),
    )
    if error:
        st.session_state.flash = error
        return
    update_item(item_id, name, qty)
    st.session_state.editing_id = None


def on_cancel_edit() -> None:
    st.session_state.editing_id = None


def on_toggle(item_id: int) -> None:
    toggle_item(item_id)


def on_delete(item_id: int) -> None:
    delete_item(item_id)
    if st.session_state.editing_id == item_id:
        st.session_state.editing_id = None


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
def inject_css() -> None:
    """스타일은 이 함수 한 곳에 모은다."""
    st.markdown(
        f"""
<style>
.block-container {{ padding-top: 2.5rem; }}

/* 목록 행: 한 줄로 유지하고 줄 사이에 구분선을 둔다 (휴대폰에서도 세로로 쌓이지 않게) */
[class*="st-key-row_"] {{ border-bottom: 1px solid {LINE}; padding: 0.2rem 0; }}
[class*="st-key-row_"] [data-testid="stHorizontalBlock"],
[data-testid="stForm"] [data-testid="stHorizontalBlock"] {{
    flex-wrap: nowrap !important; gap: 0.4rem !important; align-items: center;
}}
[class*="st-key-row_"] [data-testid="stColumn"],
[data-testid="stForm"] [data-testid="stColumn"] {{ min-width: 0 !important; }}

/* 항목 이름: 2줄까지 보여 주고 전체는 마우스 툴팁(title)으로 확인. 완료 항목은 취소선 + 흐리게 */
.item-name {{
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
    overflow: hidden; overflow-wrap: anywhere; line-height: 1.35;
}}
.item-name.done {{ text-decoration: line-through; opacity: 0.5; }}

/* 수량 배지 */
.qty-badge {{
    display: inline-block; padding: 1px 10px; border-radius: 999px;
    background: {ACCENT_SOFT}; border: 1px solid {ACCENT};
    font-size: 0.85rem; font-weight: 600; white-space: nowrap;
}}

/* 행 안의 버튼은 작게. 좁은 화면에서는 아이콘만 보이고 글자는 접근성용으로만 남긴다 */
[class*="st-key-row_"] button {{ min-height: 2.2rem; padding: 0.1rem 0.5rem; }}
@media (max-width: 640px) {{
    [class*="st-key-row_todo_"] button [data-testid="stMarkdownContainer"],
    [class*="st-key-row_done_"] button [data-testid="stMarkdownContainer"] {{ display: none; }}
}}

/* 주 버튼은 라이트/다크 모두에서 같은 초록으로 */
[data-testid^="stBaseButton-primary"] {{ background-color: {ACCENT}; border-color: {ACCENT}; }}
[data-testid^="stBaseButton-primary"]:hover {{ background-color: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
[data-testid^="stBaseButton-primary"] p {{ color: #fff; }}

/* 빈 목록 */
.empty-state {{ text-align: center; padding: 2.5rem 0; opacity: 0.85; }}
.empty-state .emoji {{ font-size: 3.2rem; line-height: 1.2; }}
</style>
""",
        unsafe_allow_html=True,
    )


def render_header(items: list[dict]) -> None:
    done = sum(1 for i in items if i["checked"])
    st.title("🛒 쇼핑 리스트")
    st.progress(
        done / len(items) if items else 0.0,
        text=f"전체 {len(items)}개 · 완료 {done}개",
    )


def render_add_form() -> None:
    # 수량의 범위(1~99)는 min/max 대신 on_add에서 검사한다.
    # min/max를 쓰면 범위 밖 값에서 제출이 아무 안내 없이 막히기 때문이다.
    with st.form("add_form", clear_on_submit=True):
        col_name, col_qty, col_btn = st.columns([6, 2.4, 2], vertical_alignment="bottom")
        col_name.text_input("물건 이름", key="new_name", placeholder="예: 우유")
        col_qty.number_input("수량", value=1, step=1, key="new_qty")
        col_btn.form_submit_button(
            "추가", on_click=on_add, type="primary", use_container_width=True
        )


def render_item_row(item: dict) -> None:
    item_id = item["id"]
    if st.session_state.editing_id == item_id:
        with st.container(key=f"row_edit_{item_id}"):
            col_name, col_qty, col_save, col_cancel = st.columns(
                [5, 2.4, 1.6, 1.6], vertical_alignment="bottom"
            )
            col_name.text_input("이름", key=f"edit_name_{item_id}")
            col_qty.number_input("수량", step=1, key=f"edit_qty_{item_id}")
            col_save.button(
                "저장", key=f"save_{item_id}", on_click=on_save_edit, args=(item_id,),
                type="primary", help="수정 내용 저장",
            )
            col_cancel.button(
                "취소", key=f"cancel_{item_id}", on_click=on_cancel_edit, help="수정 취소"
            )
        return

    row_key = f"row_done_{item_id}" if item["checked"] else f"row_todo_{item_id}"
    with st.container(key=row_key):
        col_chk, col_name, col_qty, col_edit, col_del = st.columns(
            [0.9, 5, 1.5, 1.1, 1.1], vertical_alignment="center"
        )
        # 체크 상태의 기준은 DB다. 새로고침이나 다른 탭의 변경이 있어도 DB 값으로 맞춘다.
        st.session_state[f"chk_{item_id}"] = item["checked"]
        # 라벨은 마크다운으로 렌더링되므로 이름을 넣지 않는다. (숨겨진 라벨에서도 URL이 링크로 바뀐다.)
        col_chk.checkbox(
            "완료 표시", key=f"chk_{item_id}", on_change=on_toggle, args=(item_id,),
            label_visibility="collapsed",
        )
        # 이름은 마크다운으로 해석하지 않고 HTML 이스케이프한 글자 그대로 그린다.
        # (마크다운을 거치면 URL이 링크로 바뀌고 이스케이프 문자가 보이는 문제가 있었다.)
        safe_name = html.escape(item["name"], quote=True)
        css_class = "item-name done" if item["checked"] else "item-name"
        col_name.html(f'<span class="{css_class}" title="{safe_name}">{safe_name}</span>')
        col_qty.markdown(
            f'<span class="qty-badge">x{int(item["quantity"])}</span>', unsafe_allow_html=True
        )
        col_edit.button(
            "수정", key=f"edit_{item_id}", on_click=on_start_edit, args=(item_id,),
            type="tertiary", icon=":material/edit:", help="수정",
        )
        col_del.button(
            "삭제", key=f"del_{item_id}", on_click=on_delete, args=(item_id,),
            type="tertiary", icon=":material/delete:", help="삭제",
        )


def render_list(items: list[dict]) -> None:
    if not items:
        st.markdown(
            '<div class="empty-state"><div class="emoji">🧺</div>'
            "<p>아직 항목이 없어요.<br>위에서 물건을 추가해 보세요.</p></div>",
            unsafe_allow_html=True,
        )
        return
    # 미완료는 위, 완료는 아래 (표시 순서만 바꾸고 데이터 순서는 그대로 둔다)
    for item in sorted(items, key=lambda i: i["checked"]):
        render_item_row(item)
    if any(i["checked"] for i in items):
        st.button("체크한 항목 지우기", key="clear_checked", on_click=clear_checked)


def main() -> None:
    st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")
    init_state()
    inject_css()
    items = list_items()
    render_header(items)
    render_add_form()
    flash = st.session_state.flash
    if flash:
        st.warning(flash)
        st.session_state.flash = None
    render_list(items)


main()
