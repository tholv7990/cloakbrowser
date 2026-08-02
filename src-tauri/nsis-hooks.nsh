; Plasma NSIS installer hooks (Tauri v2 `bundle.windows.nsis.installerHooks`).
;
; On uninstall, ask — as a separate, explicit question — whether to ALSO delete the
; user's local browser profiles + data. Default is Keep, so a reinstall restores
; everything. Only the new-layout data root (%LOCALAPPDATA%\Plasma) is removed; a
; legacy %LOCALAPPDATA%\CloakBrowser\Manager root is never touched by the uninstaller
; (safety — an adopted-legacy install keeps its data regardless of this choice).

; Stop the shell before its supervised backend so an older shell cannot respawn the
; sidecar while this installer replaces it. The generated installer repeats the shell
; check after this hook; the second check closes any late-start race.
!define PLASMA_NSIS_HOOK_DIR "${__FILEDIR__}"

!macro StopInstalledSidecar
  InitPluginsDir
  File "/oname=$PLUGINSDIR\stop-installed-sidecar.ps1" \
    "${PLASMA_NSIS_HOOK_DIR}\stop-installed-sidecar.ps1"
  ${If} ${RunningX64}
    ; NSIS is 32-bit. Sysnative bypasses WOW64 redirection so Get-Process.Path
    ; can inspect the installed 64-bit sidecar rather than silently returning null.
    StrCpy $R7 "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  ${Else}
    StrCpy $R7 "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
  ${EndIf}
  nsExec::ExecToStack '"$R7" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\stop-installed-sidecar.ps1" -TargetPath "$INSTDIR\plasma-backend.exe"'
  Pop $R8
  Pop $R9
  ${If} $R8 != 0
    DetailPrint "$R9"
    Abort "Failed to stop the installed Plasma backend. Close Plasma and try again."
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"
  !insertmacro StopInstalledSidecar
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
    "Also delete your local Plasma browser profiles and data?$\n$\nChoose No to keep them for a future reinstall." \
    /SD IDNO IDNO plasma_keep_local_data
    RMDir /r "$LOCALAPPDATA\Plasma"
  plasma_keep_local_data:
!macroend
