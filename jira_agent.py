import os
import re
import sys
from types import SimpleNamespace
from typing import Annotated, Any, List
from typing_extensions import TypedDict
from jira import JIRA
from langgraph.graph import StateGraph, START, END

from app.config.env_loader import load_project_env
from app.services.ai_mode_context_service import get_non_portal_ai_mode
from app.services.llm_router_service import (
    TASK_REQUIREMENT_ANALYSIS,
    call_text_llm,
)

# 1. Load environment configurations from .env
load_project_env()

class RouterLLMProxy:
    def invoke(self, prompt: str):
        content = call_text_llm(
            task_type=TASK_REQUIREMENT_ANALYSIS,
            prompt=prompt,
            ai_mode=get_non_portal_ai_mode(),
            source_channel="legacy_jira_agent",
        )
        return SimpleNamespace(content=content)


llm = RouterLLMProxy()

# 3. Define the Graph State with a subtask queue
class JiraLoopingState(TypedDict):
    ticket_id: str               # Main Jira Ticket ID
    subtask_queue: List[str]     # Queue of sub-ticket keys left to process
    current_context: str         # The continuously growing/refined requirements context
    qa_ambiguities: str          # Final Q&A ambiguities table
    summarized_req: str          # Final structured business requirements summary


# ==========================================
# 🔌 NODE 1: Fetch Main Ticket and Initialize the Subtask Queue
# ==========================================
def fetch_main_ticket_node(state: JiraLoopingState) -> dict[str, Any]:
    ticket_key = state["ticket_id"]
    # Đọc cấu hình hàng đợi truyền sang ban đầu từ Telegram Bot
    incoming_queue = state.get("subtask_queue", [])
    
    print(f"\n[Step 1] 🔌 Connecting to Jira to fetch main ticket {ticket_key}...")
    
    try:
        jira_options = {'server': os.getenv("JIRA_SERVER_URL")}
        if os.getenv("JIRA_API_TOKEN") and not os.getenv("JIRA_USERNAME"):
            jira_client = JIRA(options=jira_options, token_auth=os.getenv("JIRA_API_TOKEN"))
        else:
            jira_client = JIRA(options=jira_options, basic_auth=(os.getenv("JIRA_USERNAME"), os.getenv("JIRA_API_TOKEN")))
        
        issue = jira_client.issue(ticket_key)
        summary = issue.fields.summary or "No Title"
        description = issue.fields.description or "No detailed description provided."
        
        initial_context = f"=== MAIN TICKET: {ticket_key} ===\nTITLE: {summary}\nDESCRIPTION:\n{description}\n\n"
        
        # Fetch Main Ticket Comments
        comments = issue.fields.comment.comments
        if comments:
            initial_context += "--- MAIN TICKET COMMENTS ---\n"
            for idx, comment in enumerate(comments, start=1):
                author = comment.author.displayName if hasattr(comment.author, 'displayName') else "Anonymous"
                body = comment.body or ""
                initial_context += f"[{idx}] {author}: {body}\n"
            initial_context += "\n"
            
        # ĐOẠN SỬA LỖI LOGIC: Kiểm tra cấu hình nút bấm Telegram trước khi quét Jira
        if incoming_queue == ["SKIP_LOOP"]:
            print("🚫 User chose 'No, main ticket only'. Skipping sub-tickets detection completely.")
            final_queue = ["SKIP_LOOP"]
        else:
            # Nếu người dùng chọn YES hoặc chạy tự động, tiến hành quét danh sách sub-tasks thật từ Jira
            subtasks = issue.fields.subtasks
            final_queue = [subtask.key for subtask in subtasks] if subtasks else []
            print(f"🌿 Detected {len(final_queue)} sub-tickets added to processing queue.")
        
        return {"current_context": initial_context, "subtask_queue": final_queue}
    except Exception as e:
        return {"current_context": f"❌ Jira connection error: {e}", "subtask_queue": []}

# 🔄 NODE 2: Fetch ONE Sub-ticket and Stream/Merge into Context using DeepSeek
def fetch_and_merge_subtask_node(state: JiraLoopingState) -> dict[str, Any]:
    queue = state["subtask_queue"].copy()
    current_context = state["current_context"]
    
    # Pop the first sub-ticket from the queue
    sub_key = queue.pop(0)
    print(f"🔄 Processing sub-ticket {sub_key}... ({len(queue)} left in queue)")
    
    try:
        jira_options = {'server': os.getenv("JIRA_SERVER_URL")}
        if os.getenv("JIRA_API_TOKEN") and not os.getenv("JIRA_USERNAME"):
            jira_client = JIRA(options=jira_options, token_auth=os.getenv("JIRA_API_TOKEN"))
        else:
            jira_client = JIRA(options=jira_options, basic_auth=(os.getenv("JIRA_USERNAME"), os.getenv("JIRA_API_TOKEN")))
            
        sub_issue = jira_client.issue(sub_key)
        sub_summary = sub_issue.fields.summary or "No Title"
        sub_desc = sub_issue.fields.description or "No description."
        
        sub_content = f"=== SUB-TICKET: {sub_key} - {sub_summary} ===\nDESCRIPTION:\n{sub_desc}\n"
        
        sub_comments = sub_issue.fields.comment.comments
        if sub_comments:
            sub_content += "COMMENTS:\n"
            for s_idx, s_comment in enumerate(sub_comments, start=1):
                s_author = s_comment.author.displayName if hasattr(s_comment.author, 'displayName') else "Anonymous"
                sub_content += f"  [{s_idx}] {s_author}: {s_comment.body}\n"
        
        # Use DeepSeek to incrementally blend this specific sub-ticket information into the existing context
        prompt = f"""
        You are an expert Requirements Engineer. Your task is to update and enrich the existing requirements context by blending in the newly discovered sub-ticket details.
        
        EXISTING REQUIREMENTS CONTEXT:
        ---
        {current_context}
        ---
        
        NEW SUB-TICKET DATA TO INTEGRATE:
        ---
        {sub_content}
        ---
        
        Task: Review the new sub-ticket data. Append, refine, or update the existing context. If the sub-ticket modifies or details any workflow already mentioned in the context, synthesize them cleanly so there are no contradictions. Keep all information structured in technical English.
        
        Return ONLY the updated comprehensive context text.
        """
        response = llm.invoke(prompt)
        return {"current_context": response.content, "subtask_queue": queue}
        
    except Exception as e:
        print(f"⚠️ Failed to process sub-ticket {sub_key}: {e}")
        return {"subtask_queue": queue}

# 🔄 ROUTER FUNCTION: Check if the subtask queue is empty
def should_continue(state: JiraLoopingState) -> str:
    queue = state.get("subtask_queue", [])
    
    # ĐIỀU KIỆN SỬA LỖI: Nếu hàng đợi trống, hoặc chứa cờ SKIP_LOOP -> NGẮT LUÔN, đi thẳng tới finalize
    if not queue or queue == ["SKIP_LOOP"] or "SKIP_LOOP" in queue:
        return "finalize"
        
    # Chỉ lặp khi danh sách chứa các mã ticket thật sự hợp lệ
    return "process_subtask"





# ==========================================
# CẤU HÌNH ĐỒ THỊ VÒNG LẶP TIN GỌN (JIRA FETCHER ONLY)
# ==========================================
workflow = StateGraph(JiraLoopingState)

# 1. Chỉ đăng ký đúng 2 Node làm nhiệm vụ cào dữ liệu kỹ thuật
workflow.add_node("main_ticket_fetcher", fetch_main_ticket_node)
workflow.add_node("subtask_processor", fetch_and_merge_subtask_node)

# 2. Xây dựng sơ đồ đường đi và kết nối điều hướng vòng lặp
workflow.add_edge(START, "main_ticket_fetcher")

# Sau khi đọc main ticket, gọi hàm kiểm tra xem có cần lặp qua subtask không
workflow.add_conditional_edges(
    "main_ticket_fetcher",
    should_continue,
    {
        "process_subtask": "subtask_processor",
        "finalize": END  # ĐÃ ADD VÀO ĐÂY: Kết thúc đồ thị ngay lập tức nếu chọn NO hoặc không có subtask
    }
)

# Sau khi xử lý xong 1 subtask, tiếp tục kiểm tra hàng đợi để lặp tiếp hoặc kết thúc
workflow.add_conditional_edges(
    "subtask_processor",
    should_continue,
    {
        "process_subtask": "subtask_processor",  # Quay vòng lại nếu còn subtask trong hàng đợi
        "finalize": END  # ĐÃ ADD VÀO ĐÂY: Hết hàng đợi thì kết thúc đồ thị luôn
    }
)

# Biên dịch ứng dụng Fetcher
jira_agent_app = workflow.compile()

# ==========================================
# LOCAL RUNNER ENTRYPOINT FOR TESTING
# ==========================================
if __name__ == "__main__":
    print("🤖 Jira Fetcher Agent (Local Test Mode) Activated!")
    print("--------------------------------------------------")
    target_ticket = input("👉 Enter Jira Ticket ID to analyze (e.g., SEC-102): ").strip()
    print("--------------------------------------------------")
    
    if not target_ticket:
        print("❌ Invalid Ticket ID provided!")
    else:
        # Khởi tạo dữ liệu đầu vào cho đồ thị tuần hoàn
        initial_inputs = {
            "ticket_id": target_ticket, 
            "subtask_queue": [], 
            "current_context": ""
        }
        
        # Kích hoạt chạy đồ thị kéo dữ liệu
        final_outputs = jira_agent_app.invoke(initial_inputs)
        
        print("\n" + "="*50)
        print(f"🚀 CONSOLIDATED RAW DATA FETCHED FOR {target_ticket}:")
        print("="*50 + "\n")
        # In ra kho dữ liệu thô tổng hợp (đã bao gồm main ticket, comments và subtasks)
        print(final_outputs["current_context"])
