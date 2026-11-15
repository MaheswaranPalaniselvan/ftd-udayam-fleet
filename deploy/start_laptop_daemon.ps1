Set-Location 'C:\Users\ELCOT\udayam'
$env:PATH = "C:\Users\ELCOT\.local\bin;$env:PATH"
& "C:\Users\ELCOT\.local\bin\uv.exe" run python client/app.py --cli --machine "Laptop-Ryzen-ELCOT" --concurrency 3 --no-auto-update *> daemon.log

