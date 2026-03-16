from PySide6.QtGui import QShortcut,QKeySequence

def register(window,controller):

    QShortcut(QKeySequence("A"),window,controller.accept)
    QShortcut(QKeySequence("D"),window,controller.discard)
    QShortcut(QKeySequence("P"),window,controller.previous)
    QShortcut(QKeySequence("S"),window,controller.skip_file)
    QShortcut(QKeySequence("Ctrl+S"),window,controller.save)
    QShortcut(QKeySequence("Q"),window,controller.quit)