# Sandworm Research Agent Kit

ชุด workflow วิจัยที่ใช้ **Pydantic AI 2.67.0** รับข้อความจากแหล่งข้อมูลที่คุณเตรียมไว้ แล้วสร้างแถวหลักฐานพร้อม URL, ภูมิภาค, เวอร์ชัน และสถานะ `NR` เมื่อข้อมูลไม่พอ

## สิ่งที่เราพัฒนาเพิ่ม

1. ตรวจรายการคำถาม รหัสแหล่งข้อมูล และขอบเขตแหล่งที่แต่ละคำถามใช้อ้างอิงได้
2. เรียก Agent เพื่อสร้างผลตาม schema หนึ่งรอบ ไม่มีเครื่องมือเปิดเว็บหรือรันโค้ด
3. ตรวจซ้ำด้วยโค้ด: ข้อความ claim ต้องตรงกับ excerpt และต้องพบข้อความนั้นในต้นฉบับ แหล่งอ้างอิงนอกขอบเขตหรือข้อมูลที่โมเดลแต่งเพิ่มจะถูกปฏิเสธ
4. ส่งออกหลักฐาน, SHA-256, ชุดคำตอบสำหรับ Thai Eval Studio และ JSONL สำหรับ AI Run Ledger

การตรวจข้อความตรงต้นฉบับ **ไม่ได้รับรองว่าต้นฉบับเป็นความจริงหรือว่าข้อความนั้นตอบคำถามได้ถูกต้อง** ผู้ใช้ต้องตรวจความเกี่ยวข้องและความน่าเชื่อถือเอง ข้อมูลเกมในตัวอย่างเป็นข้อมูลสมมติทั้งหมด

## เริ่มใช้งาน

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/sandworm-research examples/study.json --fixture-draft examples/draft.json --output output/fixture
```

Windows ใช้ `.venv\Scripts\python.exe` แทน ต้องใช้ Python 3.11 ขึ้นไป ไม่ต้องมี GPU และไม่ต้องมี API key สำหรับตัวอย่างหรือชุดทดสอบ

โหมดตัวอย่างใช้ FunctionModel ของ Pydantic AI จริง แต่คำตอบถูกกำหนดไว้ล่วงหน้า ไม่ได้ให้ LLM คิดคำตอบ และจำนวน token เป็นค่าประมาณจากกรอบทดสอบ รายงานระบุ `fixture` ชัดเจน

ผลลัพธ์ 4 ไฟล์อยู่ในโฟลเดอร์ใหม่ที่กำหนด:

- `report.json`: แถวหลักฐาน ข้อมูลต้นทาง hash และข้อจำกัด
- `thai_eval_candidates.json`: นำเข้าช่องคำตอบของ Thai Eval
- `thai_eval_contract_dataset.json`: ตรวจรูปแบบ citation/การงดตอบเท่านั้น ต้องเขียนเกณฑ์คำตอบที่เป็นอิสระเพิ่มก่อนใช้วัดคุณภาพ
- `ledger.jsonl`: นำเข้า AI Run Ledger โดยตัวอย่างใช้ชื่อโมเดลสมมติ `synthetic-research-model` หากรวมหลายรอบ ต้องตั้ง ID แต่ละ attempt ให้ไม่ซ้ำ

## เรียกโมเดลจริง

ตั้ง `OPENAI_API_KEY` ผ่าน environment ของระบบจัดการ secret เลือกโมเดล Responses API เอง และแก้ราคาใน `examples/budget.json` ให้ตรงราคาที่คุณใช้ ราคาตัวอย่างไม่ใช่ราคาปัจจุบันของผู้ให้บริการ

```sh
.venv/bin/sandworm-research examples/study.json --live --model YOUR_RESPONSES_MODEL --budget examples/budget.json --output output/live
```

โหมดนี้ส่งข้อความต้นทางทั้งหมดไป OpenAI API ทางการ ไม่เปิด URL ที่ระบุในเอกสาร มีการตรวจงบตามราคาที่คุณตั้งก่อนเรียก ตรวจจำนวน token ของบริบทก่อนสร้างคำตอบ จำกัดหนึ่ง response ปิดการ retry และกำหนดเวลา/จำนวน token ขาออก การตรวจ token อาจมี API request เพิ่ม ส่วน cost guard อาจตรวจพบเกินงบหลังได้คำตอบ จึงไม่ใช่การรับรองเพดานบิลจริง ควรตั้งวงเงินที่บัญชีผู้ให้บริการด้วย

ระหว่างพัฒนาไม่ได้เรียก paid model API ทดสอบเฉพาะ Pydantic AI FunctionModel และ TestModel ในเครื่องคลาวด์

## ข้อมูลและข้อจำกัด

JSON UTF-8 สูงสุด 512 KiB, 64 แหล่งข้อมูล, 32 คำถาม; ไม่รับ key ซ้ำ ค่า NaN หรือฟิลด์นอก schema URL ต้องเป็น HTTPS และไม่มีรหัสผ่าน/query/fragment URL เป็นเพียงข้อมูลอ้างอิง ไม่มีการเข้าไปอ่านอัตโนมัติ

ไฟล์ผลลัพธ์มีข้อความ excerpt และชื่อแหล่งข้อมูล จึงต้องตรวจทานก่อนแชร์ ข้อความผิดพลาดแสดงเฉพาะรหัส ไม่ใส่ข้อมูลดิบหรือ exception ของโมเดล ไม่มีฐานข้อมูลประวัติหรือการส่งแจ้งเตือนอัตโนมัติ

ทดสอบด้วย `.venv/bin/python scripts/validate.py` และ `node --test tests/web.test.cjs` ดูรายละเอียดภาษาอังกฤษใน [README.md](README.md) และขอบเขตความปลอดภัยใน [SECURITY.md](SECURITY.md)
