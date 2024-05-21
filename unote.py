from tkinter import *
import sys
import markdown
import os
import subprocess
import tkinter.scrolledtext as scrolledtext
from tkinter import simpledialog
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
    filename = fd.askopenfilename(title="Select a file", filetypes=[("All Files","*.md")])#,
                                                                   # ("*.md","*.md"),
                                                                   # ("*.txt","*.txt"),
                                                                   # ("*.sql","*.sql"),
                                                                   # ("*.csv","*.csv"),
                                                                   # ("*.java","*.java"),
                                                                   # ("*.sh","*.sh"),
                                                                   # ("*.py","*.py")
                                                                    #])
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
    #HTML
    html = markdown.markdown(txt.get("1.0", END))
    file2 = open("markdown.html",'w')
    file2.write(html)
    file2.close
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

def mnu_View():
    os.system("start ./markdown.html")
    root.title("UNote -" + filename)    
    
def mnu_Refresh():
    global filename
    txt.delete('1.0', END)
    opentxt  = open(filename,'r').read()
    txt.insert( INSERT , opentxt)
    root.title("UNote -" + filename)
   

def mnu_RunCmd():
    global filename
    scmd = simpledialog.askstring("Run", "Enter command to run:")
    if scmd is not None:
       subprocess.call([scmd.strip(), filename])

def donothing():
    filewin = Toplevel(root)
    button = Button(filewin, text="Do nothing")
    button.pack()

#Main Window
root = Tk(className='UNote')
root.geometry("800x600")
root.title("UNote - Written by Theo Uys")
img = PhotoImage(file='.\icon.png')
root.iconphoto(False,img)

ar = len(sys.argv)


#Menu
menubar = Menu(root)
filemenu = Menu(menubar, tearoff=0)
filemenu.add_command(label=" New  ", command=mnu_New)
filemenu.add_command(label=" Open <Ctrl+o> ", command=mnu_Open)
filemenu.add_command(label=" Save <Ctrl+s>", command=mnu_Save)
filemenu.add_command(label=" Save As  ", command=mnu_SaveAs)
filemenu.add_command(label=" Refresh  ", command=mnu_Refresh)
filemenu.add_command(label=" Close  ", command=mnu_Close)
filemenu.add_command(label=" View  ", command=mnu_View)

filemenu.add_separator()

filemenu.add_command(label=" Run Command ", command=mnu_RunCmd)
filemenu.add_command(label=" Exit <Ctrl+x>", command=root.quit)
menubar.add_cascade(label="File", menu=filemenu)


root.config(menu=menubar)
root.configure(cursor="dotbox green")

txt = scrolledtext.ScrolledText(root,undo=True)
txt.pack(expand=True, fill=BOTH)
txt.config(wrap="none",padx=10,pady=10, bg='lightgray', fg='black')




txt.config(xscrollcommand=set,yscrollcommand=set)
#txt.config(vbar=True)
txt['font'] = ('Courier','14')


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