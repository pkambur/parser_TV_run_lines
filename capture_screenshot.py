import os
import shlex
import subprocess

# Взяли видео из кода для плеера TODO: надо самим писать
url_video = "https://rutube.ru/play/embed/88f6485ee28d56daf13302ac6fe3d931"

# Установка ffmpeg
# https://www.geeksforgeeks.org/how-to-install-ffmpeg-on-windows/

dir = "screenshots"
file_name = "screenshot_%04d.jpg"
#screenshots_path = os.path.join(dir, file_name)
screenshots_path = f"{dir}/{file_name}"
# на веб странице нашли ссылку на поток m3u8 TODO: для автоматизации надо парсить url_video и получать m3u8 ссылку
url_m3u8 = "https://e2-online-video.rbc.ru/online2/rbctvhd_1080p/index.m3u8?e=e2&t=Izzi0I"

# каждую минуту fps=1/60
# каждую 10ю секунду fps=1/10
# каждую 11ю секунду fps=1/11
# статья по crop https://annimon.com/article/3995
# -vf crop=ширина:высота:x:y 1920:1080 TODO: надо заранее знать откуда вырезать и размер выреза!
#  353:958- точка, откуда вырезаем 1474:50 - итоговый размер
command0 = f"c:/Program Files/ffmpeg/bin/ffmpeg.exe -i \"{url_m3u8}\" -vf \"fps=1/14,crop=1474:50:353:958\" {screenshots_path} -hide_banner"
# print(command0)

# Описание как запустить процесс
# https://stackoverflow.com/questions/72738553/how-can-i-run-an-ffmpeg-command-in-a-python-script
command = shlex.split(command0)
# print(command)
subprocess.run(command)