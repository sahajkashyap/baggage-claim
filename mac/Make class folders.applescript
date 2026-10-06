-- Make class folders: drop a screenshot (or a Word, CSV or text file) of a class
-- list on this icon, or copy the names and double-click it. One question, the
-- class folder name; then the child folders appear in Google Drive and a page
-- of name labels on the Desktop. Everything runs on this Mac (class_setup.py).
-- Build: osacompile -o "$HOME/Desktop/Make class folders.app" "mac/Make class folders.applescript"

property title : "Make class folders"

on open theFiles
	makeClass(POSIX path of item 1 of theFiles)
end open

on run
	makeClass("")
end run

on makeClass(src)
	set home to POSIX path of (path to home folder)
	set root to home & "baggage-claim"
	set listFile to root & "/.tmp/class list - check me.txt"
	set py to "cd " & quoted form of root & " && /usr/bin/python3 class_setup.py "
	try
		if src is "" then
			set found to do shell script py & "prepare --out " & quoted form of listFile
		else
			set found to do shell script py & "prepare --source " & quoted form of src & " --out " & quoted form of listFile
		end if
	on error msg
		display dialog msg buttons {"OK"} default button 1 with title title with icon caution
		return
	end try
	set className to ""
	repeat
		set names to do shell script "cat " & quoted form of listFile
		set answer to display dialog found & return & return & names & return & return & "Name for the class folder (for example: Grade 2 - Room 5 2026 to 2027):" default answer className buttons {"Cancel", "Fix a name", "Make folders"} default button 3 with title title
		set className to text returned of answer
		if button returned of answer is "Fix a name" then
			do shell script "open -e " & quoted form of listFile
			display dialog "Fix the names in TextEdit: one child per line. Then save (Command-S) and click Done." buttons {"Cancel", "Done"} default button 2 with title title
			try
				tell application "TextEdit" to close (every document whose name is "class list - check me.txt") saving yes
			end try
			set found to "The list now has " & (do shell script "grep -c . " & quoted form of listFile) & " names."
		else if className is not "" then
			exit repeat
		end if
	end repeat
	try
		set result_ to do shell script py & "build --list " & quoted form of listFile & " --class-name " & quoted form of className & " 2>&1"
		do shell script "rm -f " & quoted form of listFile
		display dialog result_ & return & return & "The class folder is in Google Drive. Print the labels page from your Desktop." buttons {"OK"} default button 1 with title title
	on error msg
		display dialog "The folders were not made: " & msg buttons {"OK"} default button 1 with title title with icon caution
	end try
end makeClass
