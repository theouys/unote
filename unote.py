from tkinter import *
import sys
import tkinter.scrolledtext as scrolledtext
from tkinter import filedialog as fd

filename = "Untitled.txt"

#New Clean text box
def mnu_New():
    global filename
    txt.delete('1.0', END)
    filename = "Untitled.txt"
    root.title("UNote -" + filename)

#Open new file
def mnu_KeyOpen(event):
    mnu_Open()

def mnu_Open():
    global filename
    txt.delete('1.0', END)
    filename = fd.askopenfilename(title="Select a file", filetypes=[("All Files","*.*"),
                                                                    ("*.txt","*.txt"),
                                                                    ("*.sql","*.sql"),
                                                                    ("*.csv","*.csv"),
                                                                    ("*.java","*.java"),
                                                                    ("*.sh","*.sh"),
                                                                    ("*.py","*.py")
                                                                    ])
    opentxt  = open(filename,'r').read()
    txt.insert( INSERT , opentxt)
    root.title("UNote -" + filename)

def mnu_KeySave(event):
    mnu_Save()

def mnu_Save():
    global filename
    a = txt.get('1.0', END)
    file = open(filename,'w')
    file.write(a)
    file.close
    root.title("UNote -" + filename)    

def mnu_SaveAs():
    global filename
    a = txt.get('1.0', END)
    filename = fd.asksaveasfile()
    filename.write(a)
    root.title("UNote -" + filename)        

def mnu_Close():
    global filename
    txt.delete('1.0', END)
    filename = "Untitled.txt"
    root.title("UNote -" + filename)

def donothing():
    filewin = Toplevel(root)
    button = Button(filewin, text="Do nothing")
    button.pack()

#Main Window
root = Tk(className='UNote')
root.geometry("800x600")
root.title("UNote - Written by Theo Uys")

ar = len(sys.argv)


#Menu
menubar = Menu(root)
filemenu = Menu(menubar, tearoff=0)
filemenu.add_command(label=" New  ", command=mnu_New)
filemenu.add_command(label=" Open <Ctrl+o> ", command=mnu_Open)
filemenu.add_command(label=" Save <Ctrl+s>", command=mnu_Save)
filemenu.add_command(label=" Save As  ", command=mnu_SaveAs)
filemenu.add_command(label=" Close  ", command=mnu_Close)

filemenu.add_separator()

filemenu.add_command(label="Exit <Ctrl+x>", command=root.quit)
menubar.add_cascade(label="File", menu=filemenu)


root.config(menu=menubar)


txt = scrolledtext.ScrolledText(root,undo=True)
txt.pack(expand=True, fill=BOTH)

if ar > 1 :
    filename = sys.argv[1]
    root.title("UNote - " + sys.argv[1])
    opentxt  = open(filename,'r').read()
    txt.insert( INSERT , opentxt)
    root.title("UNote -" + filename)

root.bind('<Control-x>', quit) 
root.bind('<Control-o>', mnu_KeyOpen) 
root.bind('<Control-s>', mnu_KeySave) 

root.mainloop()