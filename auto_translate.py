import os
import re
import glob
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tqdm import tqdm
import ctranslate2 as ct2
import sentencepiece as spm
from concurrent.futures import ThreadPoolExecutor, as_completed

class AutoTranslator:
    def __init__(self, models_path="models_nllb_3_3B_ct2_fp16", output_base_path="output", status_callback=None, progress_callback=None):
        self.models_path = Path(models_path)
        self.output_base_path = Path(output_base_path)
        self.status_callback = status_callback if status_callback else print
        self.progress_callback = progress_callback if progress_callback else (lambda c, t, s: None)
        self.translator = None
        self.sp_model = None
        self.supported_languages = {}
        self.max_tokens = 512
        self.num_beams = 1
        self.dictionary = {}

    def log(self, message, level="info"):
        self.status_callback(message, level)

    def initialize(self):
        self.log(f"Đang tải model từ: {self.models_path}")
        try:
            has_cuda = False
            try:
                if hasattr(ct2, 'cuda') and ct2.cuda.is_cuda_available():
                    has_cuda = True
            except Exception as e:
                self.log(f"Cảnh báo: Không thể kiểm tra CUDA qua ctranslate2.cuda.is_cuda_available(): {e}. Sẽ sử dụng CPU.", level="warning")
                has_cuda = False
            
            device = "cuda" if has_cuda else "cpu"
            self.log(f"Sử dụng thiết bị: {device}")
            
            self.translator = ct2.Translator(str(self.models_path), device=device)
            
            sp_model_candidates = [
                self.models_path / "sentencepiece.bpe.model",
                self.models_path / "nllb_3_3B_tokenizer.model",
                self.models_path / "tokenizer.model",
                self.models_path / "spm.model"
            ]

            sp_model_path = None
            for candidate in sp_model_candidates:
                if candidate.exists():
                    sp_model_path = candidate
                    self.log(f"Đã tìm thấy SentencePiece model tại: {sp_model_path}")
                    break
            
            if not sp_model_path:
                raise FileNotFoundError(f"SentencePiece model không tìm thấy trong thư mục: {self.models_path}. Đã thử các tên: {[c.name for c in sp_model_candidates]}")

            self.sp_model = spm.SentencePieceProcessor(model_file=str(sp_model_path))
            self._load_supported_languages()
            self.log("Đã tải model dịch và SentencePiece model thành công.")
        except Exception as e:
            self.log(f"Lỗi khi tải model: {e}", level="error")
            raise

    def _load_supported_languages(self):
        try:
            self.supported_languages = {
                "English": "eng_Latn",
                "Vietnamese": "vie_Latn",
                "Japanese": "jpn_Jpan",
                "Chinese (Simplified)": "zho_Hans",
                "Korean": "kor_Hang",
                "French": "fra_Latn",
                "Russian": "rus_Cyrl",
            }
            self.log(f"Đã tải {len(self.supported_languages)} ngôn ngữ được hỗ trợ.")
        except Exception as e:
            self.log(f"Lỗi khi tải danh sách ngôn ngữ được hỗ trợ: {e}", level="error")
            self.supported_languages = {}

    def get_supported_languages(self):
        return self.supported_languages

    def set_translation_params(self, max_tokens=512, num_beams=1):
        self.max_tokens = max_tokens
        self.num_beams = num_beams
        self.log(f"Đã cập nhật tham số dịch: Max Tokens={self.max_tokens}, Num Beams={self.num_beams}")

    def load_dictionary(self, dict_path):
        try:
            with open(dict_path, 'r', encoding='utf-8') as f:
                self.dictionary = json.load(f)
            self.log(f"Đã tải từ điển tùy chỉnh từ: {dict_path} với {len(self.dictionary)} mục.")
        except FileNotFoundError:
            self.log(f"Không tìm thấy file từ điển tại: {dict_path}", level="warning")
            self.dictionary = {}
        except json.JSONDecodeError:
            self.log(f"Lỗi định dạng JSON trong file từ điển: {dict_path}", level="error")
            self.dictionary = {}
        except Exception as e:
            self.log(f"Lỗi khi tải từ điển: {e}", level="error")
            self.dictionary = {}

    def clean_previous_data(self, game_path):
        game_name = Path(game_path).name
        extracted_dir = self.output_base_path / "extracted_game_files" / game_name
        translated_dir = self.output_base_path / "translated_game_files" / game_name
        
        if extracted_dir.exists():
            self.log(f"Đang xóa thư mục đã giải nén cũ: {extracted_dir}")
            try:
                shutil.rmtree(extracted_dir)
            except OSError as e:
                self.log(f"Lỗi khi xóa thư mục {extracted_dir}: {e}", level="error")
        if translated_dir.exists():
            self.log(f"Đang xóa thư mục đã dịch cũ: {translated_dir}")
            try:
                shutil.rmtree(translated_dir)
            except OSError as e:
                self.log(f"Lỗi khi xóa thư mục {translated_dir}: {e}", level="error")
        self.log("Đã làm sạch dữ liệu cũ (nếu có).")

    def detect_game_engine(self, game_path):
        game_path = Path(game_path)
        
        if (game_path / "package.json").exists() and (game_path / "js" / "rmmv.js").exists():
            self.log("Đã phát hiện game Engine: RPG Maker MV/MZ")
            return "RPGMakerMV"
        
        if (game_path / "renpy").exists() and any((game_path / "game").glob("*.rpyc")):
            self.log("Đã phát hiện game Engine: Ren'Py")
            return "RenPy"
        
        if (game_path / "UnityPlayer.dll").exists() or (game_path / "UnityPlayer.so").exists():
            self.log("Có thể là game Unity.", level="warning")
            return "Unity"

        self.log("Không thể phát hiện Engine game cụ thể. Sẽ xử lý các file văn bản chung.", level="warning")
        return "Generic"

    def extract_game_files(self, game_path, engine_type):
        self.log(f"Bắt đầu giải nén file game từ: {game_path} (Engine: {engine_type})")
        output_dir = self.output_base_path / "extracted_game_files" / Path(game_path).name
        output_dir.mkdir(parents=True, exist_ok=True)
        
        extracted_count = 0
        total_files = 0

        if engine_type == "RPGMakerMV":
            data_path = Path(game_path) / "data"
            if data_path.exists():
                json_files = list(data_path.glob("*.json"))
                total_files = len(json_files)
                for i, file_path in enumerate(json_files):
                    try:
                        shutil.copy(file_path, output_dir / file_path.name)
                        extracted_count += 1
                        self.progress_callback(i + 1, total_files, f"Giải nén JSON: {file_path.name}")
                    except Exception as e:
                        self.log(f"Lỗi khi copy file {file_path}: {e}", level="error")
                self.log(f"Đã giải nén {extracted_count}/{total_files} file JSON từ RPG Maker MV/MZ.")
            else:
                self.log("Không tìm thấy thư mục 'data/' cho RPG Maker MV/MZ.", level="warning")
                return False
            
        elif engine_type == "RenPy":
            self.log("Ren'Py yêu cầu công cụ ngoài để giải nén script (.rpyc).", level="warning")
            self.log("Hãy sử dụng một công cụ decompile Ren'Py như 'unrpyc' trước khi dịch.", level="warning")
            rpy_files = list((Path(game_path) / "game").glob("*.rpy"))
            if rpy_files:
                for i, file_path in enumerate(rpy_files):
                     try:
                        shutil.copy(file_path, output_dir / file_path.name)
                        extracted_count += 1
                        self.progress_callback(i + 1, len(rpy_files), f"Giải nén RPY: {file_path.name}")
                     except Exception as e:
                        self.log(f"Lỗi khi copy file {file_path}: {e}", level="error")
            if extracted_count == 0:
                self.log("Không tìm thấy file .rpy đã được decompile. Đảm bảo bạn đã decompile Ren'Py game.", level="error")
                return False

        elif engine_type == "Generic" or engine_type == "Unity":
            self.log("Đang tìm kiếm các file văn bản phổ biến (JSON, TXT, XML)...")
            text_files = []
            for ext in ["*.json", "*.txt", "*.xml"]:
                text_files.extend(list(Path(game_path).rglob(ext)))
            
            total_files = len(text_files)
            if total_files == 0:
                self.log("Không tìm thấy bất kỳ file văn bản nào để giải nén.", level="warning")
                return False

            for i, file_path in enumerate(text_files):
                relative_path = file_path.relative_to(game_path)
                target_path = output_dir / relative_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy(file_path, target_path)
                    extracted_count += 1
                    self.progress_callback(i + 1, total_files, f"Giải nén chung: {relative_path}")
                except Exception as e:
                    self.log(f"Lỗi khi copy file {file_path}: {e}", level="error")
            self.log(f"Đã giải nén {extracted_count}/{total_files} file văn bản chung.")

        else:
            self.log(f"Engine {engine_type} không được hỗ trợ giải nén tự động.", level="warning")
            return False
            
        if extracted_count > 0:
            self.log(f"Giải nén hoàn tất. Các file được lưu tại: {output_dir}")
            return True
        else:
            self.log("Không có file nào được giải nén.", level="warning")
            return False

    def fix_pre_translation_issues(self, extracted_files_path, engine_type):
        self.log(f"Bắt đầu fix lỗi trước dịch cho: {extracted_files_path} (Engine: {engine_type})")
        
        fixed_count = 0
        total_files_to_fix = 0

        if engine_type == "RPGMakerMV":
            json_files = list(Path(extracted_files_path).glob("*.json"))
            total_files_to_fix = len(json_files)
            for i, file_path in enumerate(json_files):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    def process_rpg_json_item(item):
                        if isinstance(item, dict):
                            for key, value in item.items():
                                if key in ["name", "note", "description"] and isinstance(value, (int, float)):
                                    item[key] = str(value)
                                elif isinstance(value, str):
                                    item[key] = value.replace('\u0000', '')
                                process_rpg_json_item(value)
                        elif isinstance(item, list):
                            for element in item:
                                process_rpg_json_item(element)

                    process_rpg_json_item(data)
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    fixed_count += 1
                    self.progress_callback(i + 1, total_files_to_fix, f"Fix pre-RPGMaker: {file_path.name}")
                except Exception as e:
                    self.log(f"Lỗi khi fix pre-translation file {file_path}: {e}", level="error")
        
        elif engine_type == "RenPy":
            rpy_files = list(Path(extracted_files_path).glob("*.rpy"))
            total_files_to_fix = len(rpy_files)
            for i, file_path in enumerate(rpy_files):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    new_lines = []
                    for line in lines:
                        line = re.sub(r"\{.*?\}", lambda m: m.group(0), line)
                        new_lines.append(line)
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.writelines(new_lines)
                    fixed_count += 1
                    self.progress_callback(i + 1, total_files_to_fix, f"Fix pre-RenPy: {file_path.name}")
                except Exception as e:
                    self.log(f"Lỗi khi fix pre-translation file {file_path}: {e}", level="error")

        elif engine_type == "Generic" or engine_type == "Unity":
            text_files = []
            for ext in ["*.json", "*.txt", "*.xml"]:
                text_files.extend(list(Path(extracted_files_path).rglob(ext)))
            
            total_files_to_fix = len(text_files)
            for i, file_path in enumerate(text_files):
                try:
                    if file_path.suffix == ".json":
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        def process_json_strings(obj):
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    if isinstance(v, str):
                                        obj[k] = v.replace('\u0000', '')
                                        obj[k] = obj[k].replace('\\n', '\n')
                                    else:
                                        process_json_strings(v)
                            elif isinstance(obj, list):
                                for item in obj:
                                    process_json_strings(item)
                        process_json_strings(data)
                        
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        fixed_count += 1

                    elif file_path.suffix == ".txt":
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        content = re.sub(r'\s+', ' ', content).strip()
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        fixed_count += 1
                    
                    elif file_path.suffix == ".xml":
                        import xml.etree.ElementTree as ET
                        tree = ET.parse(file_path)
                        root = tree.getroot()
                        
                        def process_xml_element(element):
                            if element.text:
                                element.text = element.text.replace('\u0000', '')
                            for child in element:
                                process_xml_element(child)
                        
                        process_xml_element(root)
                        tree.write(file_path, encoding='utf-8', xml_declaration=True)
                        fixed_count += 1
                    
                    self.progress_callback(i + 1, total_files_to_fix, f"Fix pre-Generic: {file_path.name}")

                except Exception as e:
                    self.log(f"Lỗi khi fix pre-translation file {file_path}: {e}", level="error")

        if fixed_count > 0:
            self.log(f"Đã fix {fixed_count}/{total_files_to_fix} lỗi trước dịch.")
        else:
            self.log("Không có lỗi nào được fix trước dịch hoặc không tìm thấy file để xử lý.")
        return True

    def translate_text(self, text, source_lang_code, target_lang_code):
        if not self.translator or not self.sp_model:
            raise RuntimeError("Model dịch chưa được tải. Vui lòng gọi initialize().")
        
        for original, translated in self.dictionary.items():
            text = text.replace(original, translated)

        if source_lang_code == "auto":
            tokens = self.sp_model.encode(text, out_type=str)
        else:
            tokens = self.sp_model.encode(f"__{source_lang_code}__ {text}", out_type=str)

        target_prefix_tokens = [f"__{target_lang_code}__"]
        
        try:
            results = self.translator.translate_batch(
                [tokens],
                target_prefix=[target_prefix_tokens],
                max_length=self.max_tokens,
                num_beams=self.num_beams
            )
            
            translated_tokens = results[0].hypotheses[0]
            
            if translated_tokens and translated_tokens[0] == target_prefix_tokens[0]:
                translated_tokens = translated_tokens[1:]

            translated_text = self.sp_model.decode(translated_tokens)
            return translated_text
        except Exception as e:
            self.log(f"Lỗi khi dịch văn bản: {e}", level="error")
            return f"[LỖI DỊCH]: {text}"

    def translate_game(self, extracted_files_path, params, is_continue=False):
        if not self.translator or not self.sp_model:
            self.log("Model dịch chưa được tải.", level="error")
            return False

        game_name = Path(extracted_files_path).name
        translated_output_dir = self.output_base_path / "translated_game_files" / game_name
        translated_output_dir.mkdir(parents=True, exist_ok=True)

        source_lang_code = params['source_lang']
        target_lang_code = params['target_lang']
        batch_size = params['batch_size']
        use_dictionary = params['use_dictionary']
        auto_detect = params['auto_detect']
        self.max_tokens = params.get('max_tokens', 512)
        self.num_beams = params.get('num_beams', 1)

        source_lang_nllb = self.supported_languages.get(source_lang_code, "eng_Latn") if source_lang_code != "auto" else "auto"
        target_lang_nllb = self.supported_languages.get(target_lang_code, "vie_Latn")

        if use_dictionary:
            self.load_dictionary("custom_dictionary.json")

        self.log(f"Bắt đầu dịch game từ '{extracted_files_path}' sang {target_lang_code} ({target_lang_nllb})...")
        self.log(f"Tham số: Batch Size={batch_size}, Max Tokens={self.max_tokens}, Num Beams={self.num_beams}")

        total_files = 0
        translated_count = 0
        skipped_count = 0

        files_to_translate = []
        for ext in ["*.json", "*.txt", "*.xml", "*.rpy"]:
            files_to_translate.extend(list(Path(extracted_files_path).rglob(ext)))
        
        total_files = len(files_to_translate)
        if total_files == 0:
            self.log("Không tìm thấy file văn bản nào để dịch trong thư mục đã giải nén.", level="warning")
            return False

        translation_status_file = self.output_base_path / "translation_status.json"
        translated_file_map = {}
        if is_continue and translation_status_file.exists():
            try:
                with open(translation_status_file, 'r', encoding='utf-8') as f:
                    translated_file_map = json.load(f)
                self.log(f"Đã tải trạng thái dịch từ: {translation_status_file}")
            except json.JSONDecodeError:
                self.log("Lỗi đọc file trạng thái dịch, bắt đầu dịch mới.", level="warning")
                translated_file_map = {}
        else:
            if translation_status_file.exists():
                try:
                    os.remove(translation_status_file)
                except OSError as e:
                    self.log(f"Lỗi khi xóa file trạng thái dịch cũ: {e}", level="error")

        translated_texts = []
        original_file_paths = []

        for i, file_path in enumerate(files_to_translate):
            relative_path = file_path.relative_to(extracted_files_path)
            output_file_path = translated_output_dir / relative_path
            output_file_path.parent.mkdir(parents=True, exist_ok=True)

            if str(relative_path) in translated_file_map:
                self.log(f"Bỏ qua file đã dịch: {relative_path}", level="info")
                skipped_count += 1
                self.progress_callback(translated_count + skipped_count, total_files, f"Bỏ qua: {relative_path.name}")
                if not output_file_path.exists():
                    try:
                        shutil.copy(file_path, output_file_path)
                    except Exception as e:
                        self.log(f"Lỗi khi copy file đã bỏ qua {file_path} sang {output_file_path}: {e}", level="error")
                continue

            self.log(f"Đang xử lý file: {relative_path}", level="info")
            try:
                if file_path.suffix == ".json":
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                    except json.JSONDecodeError as e:
                        self.log(f"Lỗi định dạng JSON trong file {file_path}: {e}. Bỏ qua dịch file này.", level="error")
                        shutil.copy(file_path, output_file_path) # Copy nguyên bản nếu lỗi
                        translated_file_map[str(relative_path)] = True
                        continue
                    except UnicodeDecodeError as e:
                        self.log(f"Lỗi mã hóa trong file {file_path}: {e}. Đảm bảo file được mã hóa UTF-8.", level="error")
                        shutil.copy(file_path, output_file_path)
                        translated_file_map[str(relative_path)] = True
                        continue
                    
                    texts_in_file = []
                    
                    def find_json_strings(obj):
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if isinstance(v, str) and len(v) > 0 and not v.isspace():
                                    texts_in_file.append(v)
                                find_json_strings(v)
                        elif isinstance(obj, list):
                            for item in obj:
                                if isinstance(item, str) and len(item) > 0 and not item.isspace():
                                    texts_in_file.append(item)
                                find_json_strings(item)
                    
                    find_json_strings(data)
                    
                    if not texts_in_file:
                        self.log(f"Không tìm thấy văn bản để dịch trong file JSON: {relative_path}", level="warning")
                        shutil.copy(file_path, output_file_path)
                        translated_file_map[str(relative_path)] = True
                        continue

                    translated_chunks = []
                    for k in tqdm(range(0, len(texts_in_file), batch_size), desc=f"Dịch {relative_path.name}"):
                        batch = texts_in_file[k:k + batch_size]
                        
                        processed_batch = []
                        for text_item in batch:
                            final_text = text_item
                            for original, translated in self.dictionary.items():
                                final_text = final_text.replace(original, translated)
                            processed_batch.append(final_text)

                        try:
                            if auto_detect:
                                tokens_batch = self.sp_model.encode(processed_batch, out_type=str)
                            else:
                                tokens_batch = self.sp_model.encode([f"__{source_lang_nllb}__ {t}" for t in processed_batch], out_type=str)
                            
                            target_prefix_tokens_batch = [[f"__{target_lang_nllb}__"]] * len(tokens_batch)

                            results = self.translator.translate_batch(
                                tokens_batch,
                                target_prefix=target_prefix_tokens_batch,
                                max_length=self.max_tokens,
                                num_beams=self.num_beams
                            )
                            
                            batch_translated_texts = []
                            for res in results:
                                translated_tokens = res.hypotheses[0]
                                if translated_tokens and translated_tokens[0] == target_prefix_tokens_batch[0][0]:
                                    translated_tokens = translated_tokens[1:]
                                batch_translated_texts.append(self.sp_model.decode(translated_tokens))
                            
                            translated_chunks.extend(batch_translated_texts)
                        except Exception as translate_err:
                            self.log(f"Lỗi khi gọi translate_batch cho một batch trong file {relative_path}: {translate_err}", level="error")
                            # Đảm bảo vẫn thêm các chuỗi gốc nếu dịch thất bại
                            translated_chunks.extend(processed_batch) 

                    translated_data = data
                    
                    # Iterator để cập nhật các chuỗi dịch vào cấu trúc JSON
                    translated_texts_iter = iter(translated_chunks)

                    def update_json_with_translated_strings(obj):
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if isinstance(v, str) and len(v) > 0 and not v.isspace():
                                    try:
                                        obj[k] = next(translated_texts_iter)
                                    except StopIteration:
                                        self.log("Cảnh báo: Số lượng chuỗi dịch không khớp với số chuỗi gốc trong JSON. Một số chuỗi có thể không được dịch.", level="warning")
                                        break # Dừng lại nếu hết chuỗi dịch
                                else:
                                    update_json_with_translated_strings(v)
                        elif isinstance(obj, list):
                            for i, item in enumerate(obj):
                                if isinstance(item, str) and len(item) > 0 and not item.isspace():
                                    try:
                                        obj[i] = next(translated_texts_iter)
                                    except StopIteration:
                                        self.log("Cảnh báo: Số lượng chuỗi dịch không khớp với số chuỗi gốc trong JSON. Một số chuỗi có thể không được dịch.", level="warning")
                                        break # Dừng lại nếu hết chuỗi dịch
                                else:
                                    update_json_with_translated_strings(item)
                    
                    update_json_with_translated_strings(translated_data)

                    try:
                        with open(output_file_path, 'w', encoding='utf-8') as f:
                            json.dump(translated_data, f, ensure_ascii=False, indent=2)
                        translated_count += 1
                        translated_file_map[str(relative_path)] = True
                    except OSError as e:
                        self.log(f"Lỗi ghi file {output_file_path}: {e}. Kiểm tra quyền ghi.", level="error")
                        shutil.copy(file_path, output_file_path) # Copy nguyên bản nếu lỗi ghi
                        translated_file_map[str(relative_path)] = False # Đánh dấu là chưa dịch thành công
                        
                elif file_path.suffix == ".txt" or file_path.suffix == ".rpy" or file_path.suffix == ".xml":
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                    except UnicodeDecodeError as e:
                        self.log(f"Lỗi mã hóa trong file {file_path}: {e}. Đảm bảo file được mã hóa UTF-8.", level="error")
                        shutil.copy(file_path, output_file_path)
                        translated_file_map[str(relative_path)] = True
                        continue
                    
                    lines_to_translate = []
                    original_line_map = {} # Lưu trữ ánh xạ từ nội dung đã xử lý về vị trí dòng gốc
                    
                    for idx, line in enumerate(lines):
                        line_stripped = line.strip()
                        # Loại bỏ các dòng trống, comment, và các ký tự đặc biệt không phải văn bản
                        if line_stripped and not line_stripped.startswith(('#', '//', '<!', '<?', '{', '}')) and line_stripped not in ['[', ']']:
                            # Thêm line_stripped vào dict nếu chưa có, hoặc cập nhật list các index
                            if line_stripped not in original_line_map:
                                original_line_map[line_stripped] = []
                            original_line_map[line_stripped].append(idx)
                            lines_to_translate.append(line_stripped)
                        
                    if not lines_to_translate:
                        self.log(f"Không tìm thấy văn bản để dịch trong file văn bản: {relative_path}", level="warning")
                        shutil.copy(file_path, output_file_path)
                        translated_file_map[str(relative_path)] = True
                        continue

                    translated_chunks = []
                    for k in tqdm(range(0, len(lines_to_translate), batch_size), desc=f"Dịch {relative_path.name}"):
                        batch = lines_to_translate[k:k + batch_size]
                        
                        processed_batch = []
                        for text_item in batch:
                            final_text = text_item
                            for original, translated in self.dictionary.items():
                                final_text = final_text.replace(original, translated)
                            processed_batch.append(final_text)

                        try:
                            if auto_detect:
                                tokens_batch = self.sp_model.encode(processed_batch, out_type=str)
                            else:
                                tokens_batch = self.sp_model.encode([f"__{source_lang_nllb}__ {t}" for t in processed_batch], out_type=str)
                            
                            target_prefix_tokens_batch = [[f"__{target_lang_nllb}__"]] * len(tokens_batch)

                            results = self.translator.translate_batch(
                                tokens_batch,
                                target_prefix=target_prefix_tokens_batch,
                                max_length=self.max_tokens,
                                num_beams=self.num_beams
                            )
                            
                            batch_translated_texts = []
                            for res in results:
                                translated_tokens = res.hypotheses[0]
                                if translated_tokens and translated_tokens[0] == target_prefix_tokens_batch[0][0]:
                                    translated_tokens = translated_tokens[1:]
                                batch_translated_texts.append(self.sp_model.decode(translated_tokens))
                            
                            translated_chunks.extend(batch_translated_texts)
                        except Exception as translate_err:
                            self.log(f"Lỗi khi gọi translate_batch cho một batch trong file {relative_path}: {translate_err}", level="error")
                            # Đảm bảo vẫn thêm các chuỗi gốc nếu dịch thất bại
                            translated_chunks.extend(processed_batch) 

                    final_translated_content = list(lines) # Bắt đầu với bản sao của các dòng gốc
                    translated_iter = iter(translated_chunks)
                    
                    # Cập nhật các dòng đã dịch vào vị trí chính xác
                    for original_text in lines_to_translate: # Lặp qua danh sách đã lọc để duy trì thứ tự
                        original_indices = original_line_map.get(original_text, [])
                        if original_indices:
                            try:
                                translated_text = next(translated_iter)
                                for idx in original_indices:
                                    final_translated_content[idx] = translated_text + '\n' # Giữ nguyên xuống dòng
                            except StopIteration:
                                self.log("Cảnh báo: Số lượng chuỗi dịch không khớp với số chuỗi gốc. Một số dòng có thể không được dịch.", level="warning")
                                break # Dừng lại nếu hết chuỗi dịch

                    try:
                        with open(output_file_path, 'w', encoding='utf-8') as f:
                            f.writelines(final_translated_content)
                        translated_count += 1
                        translated_file_map[str(relative_path)] = True
                    except OSError as e:
                        self.log(f"Lỗi ghi file {output_file_path}: {e}. Kiểm tra quyền ghi.", level="error")
                        shutil.copy(file_path, output_file_path) # Copy nguyên bản nếu lỗi ghi
                        translated_file_map[str(relative_path)] = False # Đánh dấu là chưa dịch thành công

                self.progress_callback(translated_count + skipped_count, total_files, f"Dịch: {relative_path.name}")

            except Exception as e:
                self.log(f"Lỗi không xác định khi xử lý file {relative_path}: {e}", level="error")
                if not output_file_path.exists():
                    try:
                        shutil.copy(file_path, output_file_path)
                    except Exception as copy_err:
                        self.log(f"Không thể copy file gốc {file_path} sau lỗi: {copy_err}", level="error")
                translated_file_map[str(relative_path)] = False # Đánh dấu là không thành công

        try:
            with open(translation_status_file, 'w', encoding='utf-8') as f:
                json.dump(translated_file_map, f, indent=4)
            self.log(f"Đã lưu trạng thái dịch vào: {translation_status_file}")
        except Exception as e:
            self.log(f"Lỗi khi lưu trạng thái dịch: {e}", level="error")

        self.log(f"Hoàn tất quá trình dịch. Đã dịch {translated_count} file, bỏ qua {skipped_count} file.")
        return translated_count > 0

    def fix_post_translation_issues(self, translated_files_path, engine_type):
        self.log(f"Bắt đầu fix lỗi sau dịch cho: {translated_files_path} (Engine: {engine_type})")
        
        fixed_count = 0
        total_files_to_fix = 0

        if engine_type == "RPGMakerMV":
            json_files = list(Path(translated_files_path).glob("*.json"))
            total_files_to_fix = len(json_files)
            for i, file_path in enumerate(json_files):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    def process_rpg_json_item_post(item):
                        if isinstance(item, dict):
                            for key, value in item.items():
                                if isinstance(value, str):
                                    value = value.replace('\\\\n', '\\n')
                                    item[key] = value
                                process_rpg_json_item_post(value)
                        elif isinstance(item, list):
                            for element in item:
                                process_rpg_json_item_post(element)
                    
                    process_rpg_json_item_post(data)
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    fixed_count += 1
                    self.progress_callback(i + 1, total_files_to_fix, f"Fix post-RPGMaker: {file_path.name}")
                except Exception as e:
                    self.log(f"Lỗi khi fix post-translation file {file_path}: {e}", level="error")

        elif engine_type == "RenPy":
            rpy_files = list(Path(translated_files_path).glob("*.rpy"))
            total_files_to_fix = len(rpy_files)
            for i, file_path in enumerate(rpy_files):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    new_lines = []
                    for line in lines:
                        line = re.sub(r'\{ (.*?)\}', r'{\1}', line)
                        line = re.sub(r'\[ (.*?) \]', r'[\1]', line)
                        new_lines.append(line)
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.writelines(new_lines)
                    fixed_count += 1
                    self.progress_callback(i + 1, total_files_to_fix, f"Fix post-RenPy: {file_path.name}")
                except Exception as e:
                    self.log(f"Lỗi khi fix post-translation file {file_path}: {e}", level="error")

        elif engine_type == "Generic" or engine_type == "Unity":
            text_files = []
            for ext in ["*.json", "*.txt", "*.xml"]:
                text_files.extend(list(Path(translated_files_path).rglob(ext)))
            
            total_files_to_fix = len(text_files)
            for i, file_path in enumerate(text_files):
                try:
                    if file_path.suffix == ".json":
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        def process_json_strings_post(obj):
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    if isinstance(v, str):
                                        obj[k] = v.replace('\\n', '\n')
                                        obj[k] = obj[k].replace('\\"', '"')
                                    else:
                                        process_json_strings_post(v)
                            elif isinstance(obj, list):
                                for item in obj:
                                    process_json_strings_post(item)
                        process_json_strings_post(data)
                        
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        fixed_count += 1

                    elif file_path.suffix == ".txt":
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        content = re.sub(r'\s{2,}', ' ', content)
                        content = content.replace(' .', '.').replace(' ,', ',')
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        fixed_count += 1
                    
                    elif file_path.suffix == ".xml":
                        import xml.etree.ElementTree as ET
                        tree = ET.parse(file_path)
                        root = tree.getroot()
                        
                        def process_xml_element_post(element):
                            if element.text:
                                element.text = element.text.replace('\u0000', '').strip()
                                element.text = element.text.replace('&amp;', '&') 
                            for child in element:
                                process_xml_element_post(child)
                        
                        process_xml_element_post(root)
                        tree.write(file_path, encoding='utf-8', xml_declaration=True)
                        fixed_count += 1

                    self.progress_callback(i + 1, total_files_to_fix, f"Fix post-Generic: {file_path.name}")

                except Exception as e:
                    self.log(f"Lỗi khi fix post-translation file {file_path}: {e}", level="error")

        if fixed_count > 0:
            self.log(f"Đã fix {fixed_count}/{total_files_to_fix} lỗi sau dịch.")
        else:
            self.log("Không có lỗi nào được fix sau dịch hoặc không tìm thấy file để xử lý.")
        return True

    def repack_game(self, translated_files_path, original_game_path, engine_type):
        self.log(f"Bắt đầu đóng gói game từ '{translated_files_path}' vào '{original_game_path}' (Engine: {engine_type})")
        
        repacked_count = 0
        total_files = 0

        original_game_path = Path(original_game_path)
        
        target_game_path = self.output_base_path / "final_translated_game" / original_game_path.name
        target_game_path.mkdir(parents=True, exist_ok=True)

        self.log(f"Sao chép toàn bộ game gốc từ '{original_game_path}' sang '{target_game_path}'...")
        try:
            if sys.platform == "win32":
                subprocess.run(['robocopy', str(original_game_path), str(target_game_path), '/E', '/COPYALL', '/DCOPY:T', '/R:1', '/W:1'], check=True, creationflags=subprocess.CREATE_NO_WINDOW) # Thêm cờ để không hiển thị cửa sổ console
            else:
                shutil.copytree(original_game_path, target_game_path, dirs_exist_ok=True)
            self.log("Sao chép game gốc hoàn tất.")
        except Exception as e:
            self.log(f"Lỗi khi sao chép game gốc: {e}", level="error")
            return False

        self.log(f"Đang ghi đè các file đã dịch từ '{translated_files_path}' vào game đích...")
        
        files_to_repack = []
        for ext in ["*.json", "*.txt", "*.xml", "*.rpy"]:
            files_to_repack.extend(list(Path(translated_files_path).rglob(ext)))
        
        total_files = len(files_to_repack)
        if total_files == 0:
            self.log("Không tìm thấy file đã dịch nào để đóng gói lại.", level="warning")
            return True

        for i, translated_file_path in enumerate(files_to_repack):
            relative_path = translated_file_path.relative_to(translated_files_path)
            destination_path = target_game_path / relative_path

            try:
                destination_path.parent.mkdir(parents=True, exist_ok=True) 
                shutil.copy(translated_file_path, destination_path)
                repacked_count += 1
                self.progress_callback(i + 1, total_files, f"Đóng gói: {relative_path.name}")
            except Exception as e:
                self.log(f"Lỗi khi ghi đè file {translated_file_path} vào {destination_path}: {e}", level="error")
        
        if engine_type == "RPGMakerMV":
            self.log("Đối với RPG Maker MV/MZ, việc ghi đè file JSON là đủ. Không cần bước đóng gói đặc biệt.", level="info")
        elif engine_type == "RenPy":
            self.log("Ren'Py yêu cầu biên dịch lại các file .rpy thành .rpyc. Vui lòng sử dụng Ren'Py SDK.", level="warning")
        elif engine_type == "Unity":
            self.log("Đóng gói cho Unity thường phức tạp và cần công cụ chuyên dụng.", level="warning")
        
        if repacked_count > 0:
            self.log(f"Đã đóng gói {repacked_count}/{total_files} file đã dịch vào game đích.")
            self.log(f"Game đã dịch hoàn chỉnh nằm tại: {target_game_path}")
            return True
        else:
            self.log("Không có file nào được đóng gói lại.", level="warning")
            return False

if __name__ == "__main__":
    translator = AutoTranslator()
    
    try:
        translator.initialize()
        
        test_game_path = "path/to/your/test/game" # THAY THẾ BẰNG ĐƯỜNG DẪN GAME THỰC TẾ CỦA BẠN
        if not Path(test_game_path).exists():
            print(f"Thư mục game thử nghiệm không tồn tại: {test_game_path}. Vui lòng tạo hoặc thay đổi đường dẫn.")
        else:
            translator.clean_previous_data(test_game_path)
            engine = translator.detect_game_engine(test_game_path)
            
            if translator.extract_game_files(test_game_path, engine):
                extracted_dir = translator.output_base_path / "extracted_game_files" / Path(test_game_path).name
                translator.fix_pre_translation_issues(extracted_dir, engine)
                
                translation_params = {
                    "source_lang": "Japanese",
                    "target_lang": "Vietnamese",
                    "batch_size": 4,
                    "use_dictionary": False,
                    "auto_detect": True
                }
                if translator.translate_game(extracted_dir, translation_params):
                    translated_dir = translator.output_base_path / "translated_game_files" / Path(test_game_path).name
                    translator.fix_post_translation_issues(translated_dir, engine)
                    translator.repack_game(translated_dir, test_game_path, engine)
                else:
                    print("Quá trình dịch không thành công.")
            else:
                print("Quá trình giải nén không thành công.")

    except Exception as e:
        print(f"Đã xảy ra lỗi nghiêm trọng: {e}")