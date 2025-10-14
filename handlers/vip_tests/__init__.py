# handlers/vip_tests/__init__.py

from .vip_entry import office_my_tests_entry, vip_go_to_test, office_shared_tests_entry
from .vip_templates import vip_send_template, vip_start_upload
from .vip_upload import vip_handle_document
from .vip_navigation import (
    vip_choose_folder, vip_nav_open, vip_nav_up, vip_choose_here, vip_create_root,
    vip_handle_root_folder_name_text,
)
from .vip_naming import vip_handle_newname_text
from .vip_duplicates import (
    vip_dup_view, vip_dup_replace, vip_replace_same, vip_replace_other, vip_rewrite_select
)
from .vip_delete import vip_delete_select, vip_delete_confirm
from .vip_images import vip_img_upload, vip_img_later
from .vip_cancel import vip_cancel
from .vip_edit_menu import (
    vip_edit_open,
    vip_edit_rewrite_from_menu,
    vip_edit_add_images_from_menu,
)
from .vip_trusted import (
    vip_trusted_open,
    vip_trusted_add_start,
    vip_trusted_remove_open,
    vip_trusted_remove_do,
    vip_trusted_handle_username_text,
    vip_trusted_pick_target,
    # ===== Запити (pending) =====
    vip_trusted_requests_open,
    vip_trusted_requests_accept_one,
    vip_trusted_requests_decline_one,
    vip_trusted_requests_accept_all,
    vip_trusted_requests_decline_all,
)
from .vip_move import (
    vip_edit_move_open,
    vip_move_pick,
    vip_move_open,
    vip_move_up,
    vip_move_choose_here,
)
# NEW: single-file add & wipe-all
from .vip_files_single import (
    vip_edit_add_single_file_start,
    vip_handle_single_index_text,
    vip_handle_single_media_file,
    vip_wipe_media_start,
    vip_wipe_media_confirm,
)

__all__ = [
    "office_my_tests_entry", "vip_go_to_test", "office_shared_tests_entry",
    "vip_send_template", "vip_start_upload",
    "vip_handle_document",
    "vip_choose_folder", "vip_nav_open", "vip_nav_up", "vip_choose_here", "vip_create_root",
    "vip_handle_root_folder_name_text",
    "vip_handle_newname_text",
    "vip_dup_view", "vip_dup_replace", "vip_replace_same", "vip_replace_other", "vip_rewrite_select",
    "vip_delete_select", "vip_delete_confirm",
    "vip_img_upload", "vip_img_later",
    "vip_cancel",
    "vip_edit_open", "vip_edit_rewrite_from_menu", "vip_edit_add_images_from_menu",
    "vip_trusted_open", "vip_trusted_add_start", "vip_trusted_remove_open", "vip_trusted_remove_do",
    "vip_trusted_handle_username_text", "vip_trusted_pick_target",
    # ===== Запити (pending) =====
    "vip_trusted_requests_open",
    "vip_trusted_requests_accept_one",
    "vip_trusted_requests_decline_one",
    "vip_trusted_requests_accept_all",
    "vip_trusted_requests_decline_all",
    "vip_edit_move_open", "vip_move_pick", "vip_move_open", "vip_move_up", "vip_move_choose_here",
    "vip_edit_add_single_file_start", "vip_handle_single_index_text", "vip_handle_single_media_file",
    "vip_wipe_media_start", "vip_wipe_media_confirm",
]
