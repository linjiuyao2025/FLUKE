; Keep the existing app identity and install records. Use a Chinese folder name
; for new installs while retaining the legacy folder on upgrades.

!macro customPageAfterChangeDir
  !define MUI_PAGE_CUSTOMFUNCTION_PRE WanxiangDirectoryPre
  !insertmacro MUI_PAGE_DIRECTORY
  !define MUI_PAGE_CUSTOMFUNCTION_PRE WanxiangInstFilesPre
!macroend

!macro customHeader
  !ifndef BUILD_UNINSTALLER
    !include StrContains.nsh

    Function WanxiangDirectoryPre
      ${If} ${isUpdated}
        Abort
      ${EndIf}

      ; An explicit /D path takes priority over our fresh-install default.
      !insertmacro GetDParameter $R0
      ${If} $R0 != ""
        Return
      ${EndIf}

      ${If} $installMode == "all"
        ${If} $hasPerMachineInstallation == "0"
          StrCpy $INSTDIR "$PROGRAMFILES64\万象来信"
        ${EndIf}
      ${Else}
        ${If} $hasPerUserInstallation == "0"
          StrCpy $INSTDIR "$LOCALAPPDATA\Programs\万象来信"
        ${EndIf}
      ${EndIf}
    FunctionEnd

    Function WanxiangInstFilesPre
      ; The directory page lets a user choose either a parent or a full app path.
      ; Preserve old English paths during upgrades and avoid a nested folder.
      ${StrContains} $0 "万象来信" $INSTDIR
      ${If} $0 != ""
        Return
      ${EndIf}
      ${StrContains} $0 "wanxiang-life-workspace" $INSTDIR
      ${If} $0 != ""
        Return
      ${EndIf}
      StrCpy $INSTDIR "$INSTDIR\万象来信"
    FunctionEnd
  !endif
!macroend
