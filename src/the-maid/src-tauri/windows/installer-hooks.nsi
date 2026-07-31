; The Maid — NSIS Installer Hooks
; Tauri v2 installerHooks: macros injected into the default NSIS template.
; ponytail: keep minimal — feature selection happens in-app (ADR 0004 hybrid wizard).

!macro NSIS_HOOK_PREINSTALL
  ; Create app data directory before first launch
  CreateDirectory "$PROFILE\.the-maid"
  CreateDirectory "$PROFILE\.the-maid\models"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Desktop shortcut (optional — user can remove)
  CreateShortcut "$DESKTOP\The Maid.lnk" "$INSTDIR\the-maid.exe" "" "$INSTDIR\the-maid.exe" 0
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; ponytail: remove shortcuts but keep user data (.the-maid folder survives uninstall)
  Delete "$DESKTOP\The Maid.lnk"
!macroend