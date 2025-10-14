; Press F9 to choose a text file, then the script will paste each line.
; Place your cursor in the first target cell/field before pressing F9.

F9:: {
    file := FileSelect("1", , "Select a text file to paste", "Text (*.txt;*.csv;*.tsv)|*.txt;*.csv;*.tsv")
    if !file
        return

    text  := FileRead(file, "UTF-8")
    lines := StrSplit(text, "`n")
    for i, line in lines
        lines[i] := RTrim(line, "`r")  ; strip CR if present

    savedClip := ClipboardAll()        ; backup clipboard
    try {
        for line in lines {
            Send("^a")
            Sleep(50)
            Send("{Backspace}")
            Sleep(40)
            Clipboard := line
            ClipWait(1)
            Send("^v")
            Sleep(40)
            Send("{Down}")
            Sleep(60)
        }
    } finally {
        Clipboard := savedClip          ; restore clipboard
        savedClip := ""
    }
}
