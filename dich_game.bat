@echo off
setlocal enabledelayedexpansion

:: Thiết lập màu cho console
color 0A

:: Tiêu đề
title Công Cụ Dịch Game - AutoTranslator

echo ====================================================================
echo             CÔNG CỤ DỊCH GAME TỰ ĐỘNG
echo             Phiên bản: 1.0.0
echo ====================================================================
echo.

:: Thiết lập đường dẫn thư mục model chính
set "MODEL_DIR=models_nllb_3_3B_ct2_fp16"
set "SPM_DIR=models_nllb_3_3B"

:: Kiểm tra Python
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [LỖI] Không tìm thấy Python. Vui lòng cài đặt Python 3.8 trở lên.
    echo Tải Python tại: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Kiểm tra thư mục model chính (CTranslate2)
echo Kiểm tra thư mục model: %MODEL_DIR%
if not exist "%MODEL_DIR%\" (
    echo [LỖI] Thư mục model CTranslate2 "%MODEL_DIR%" không tồn tại.
    echo Vui lòng tạo thư mục và đặt mô hình vào đó.
    pause
    exit /b 1
)

:: Kiểm tra file model.bin
if not exist "%MODEL_DIR%\model.bin" (
    echo [LỖI] Không tìm thấy file "model.bin" trong thư mục "%MODEL_DIR%".
    echo Đảm bảo bạn đã đặt mô hình CTranslate2 đầy đủ vào đây.
    pause
    exit /b 1
)

:: Kiểm tra thư mục SentencePiece Model
echo Kiểm tra thư mục SentencePiece Model: %SPM_DIR%
if not exist "%SPM_DIR%\" (
    echo [LỖI] Thư mục SentencePiece Model "%SPM_DIR%" không tồn tại.
    echo Vui lòng tạo thư mục và đặt file "sentencepiece.bpe.model" vào đó.
    pause
    exit /b 1
)

:: Kiểm tra file SentencePiece Model
if not exist "%SPM_DIR%\sentencepiece.bpe.model" (
    echo [LỖI] Không tìm thấy file "sentencepiece.bpe.model" trong thư mục "%SPM_DIR%".
    echo Đảm bảo bạn đã đặt file SentencePiece model vào đây.
    pause
    exit /b 1
)

echo.
echo Tất cả các file model cần thiết đã được tìm thấy.
echo.

:: Kiểm tra và cài đặt các thư viện cần thiết
echo Kiểm tra và cài đặt các thư viện cần thiết...
python -m pip install --upgrade pip > nul 2>&1

:: Danh sách các thư viện cần thiết
set "packages=ctranslate2 transformers sentencepiece tqdm numpy tkinter pillow py7zr"

:: Cài đặt từng thư viện
for %%p in (%packages%) do (
    echo Kiểm tra thư viện %%p...
    python -c "import %%p" > nul 2>&1
    if !errorlevel! neq 0 (
        echo Đang cài đặt %%p...
        python -m pip install %%p
        if !errorlevel! neq 0 (
            echo [LỖI] Không thể cài đặt thư viện %%p. Vui lòng kiểm tra kết nối mạng hoặc quyền truy cập.
            pause
            exit /b 1
        )
    ) else (
        echo %%p đã được cài đặt.
    )
)

echo.
echo Tất cả thư viện đã sẵn sàng!
echo.

:: Kiểm tra GPU (CUDA) - tùy chọn
echo Kiểm tra GPU (CUDA)...
python -c "import torch; print('CUDA khả dụng:',torch.cuda.is_available())" 2>nul
if %errorlevel% neq 0 (
    echo [THÔNG TIN] Không tìm thấy PyTorch hoặc CUDA. Sẽ sử dụng CPU cho dịch.
    echo Để tăng tốc dịch, bạn có thể cài đặt PyTorch với CUDA nếu có GPU hỗ trợ.
    echo.
) else (
    echo [THÔNG TIN] Đã tìm thấy PyTorch. CUDA khả dụng: %CUDA_AVAIL%
    echo.
)


:: Khởi động giao diện
echo ====================================================================
echo Khởi động Công Cụ Dịch Game...
echo ====================================================================
echo.

:: Chạy chương trình chính
python auto_translator_gui.py

:: Kết thúc
echo.
if %errorlevel% neq 0 (
    echo [LỖI] Chương trình kết thúc với mã lỗi: %errorlevel%
) else (
    echo Chương trình đã kết thúc thành công.
)

pause
exit /b 0