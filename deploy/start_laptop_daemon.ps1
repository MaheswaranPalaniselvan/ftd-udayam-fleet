Set-Location 'C:\Users\ELCOT\udayam'
$env:PATH = "C:\Users\ELCOT\.local\bin;$env:PATH"
$env:USERPROFILE = "C:\Users\ELCOT"
$env:LOCALAPPDATA = "C:\Users\ELCOT\AppData\Local"
$env:PLAYWRIGHT_BROWSERS_PATH = "C:\Users\ELCOT\AppData\Local\ms-playwright"
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH = "C:\Users\ELCOT\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe"

# Launch scraper daemon
& "C:\Users\ELCOT\.local\bin\uv.exe" run python client/app.py --cli --machine "Laptop-Ryzen-ELCOT" --concurrency 2 --no-auto-update *> daemon.log
