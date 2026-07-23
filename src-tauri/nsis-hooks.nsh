; Plasma NSIS installer hooks (Tauri v2 `bundle.windows.nsis.installerHooks`).
;
; On uninstall, ask — as a separate, explicit question — whether to ALSO delete the
; user's local browser profiles + data. Default is Keep, so a reinstall restores
; everything. Only the new-layout data root (%LOCALAPPDATA%\Plasma) is removed; a
; legacy %LOCALAPPDATA%\CloakBrowser\Manager root is never touched by the uninstaller
; (safety — an adopted-legacy install keeps its data regardless of this choice).

!macro NSIS_HOOK_PREUNINSTALL
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
    "Also delete your local Plasma browser profiles and data?$\n$\nChoose No to keep them for a future reinstall." \
    /SD IDNO IDNO plasma_keep_local_data
    RMDir /r "$LOCALAPPDATA\Plasma"
  plasma_keep_local_data:
!macroend
