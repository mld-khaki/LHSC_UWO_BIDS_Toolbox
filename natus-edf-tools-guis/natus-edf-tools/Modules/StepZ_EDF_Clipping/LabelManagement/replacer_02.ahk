; Press F9 to choose a text file, then the script will paste each line.
; Place your cursor in the first target cell/field before pressing F9.

F9::
    FileSelectFile, file, 3,, Select a text file to paste, Text Documents (*.txt;*.csv;*.tsv)
    if (file = "")
        return

    FileRead, text, %file%
    StringReplace, text, text, `r, , All
    lines := StrSplit(text, "`n")

    savedClip := ClipboardAll
    for index, line in lines {
        Send, ^a
        Sleep, 50
        Send, {Backspace}
        Sleep, 40
        Clipboard := line
        ClipWait, 1
        Send, ^v
        Sleep, 40
        Send, {Down}
        Sleep, 60
    }
    Clipboard := savedClip
return
