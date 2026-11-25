"""โชว์จุดเข้า-ออก BT ทั้งหมด - รันใน Render Shell
ใช้: python show_bt_all.py
- อ่าน /data/bt_results.json (ผล BT V9 ที่พี่รันไว้)
- พิมพ์ทุกไม้: เข้า / ออก / Wave / TP-SL / PnL
- ส่งเข้า Telegram แบบแบ่ง 2-3 ข้อความ (กันข้อความยาวเกิน)
- วาดกราฟ BTC + GOLD มีจุด B = เข้า LONG, S = เข้า SHORT, X = ออก ทุกไม้
ไฟล์รูปจะอยู่ที่ /data/bt_all_chart.png แล้วส่งเข้า Telegram ด้วย
"""
import json, os, requests
from pathlib import Path
DATA_DIR = Path("/data") if Path("/data").exists() else Path("/tmp")

def send_tele(msg, photo=None):
    tok = os.getenv("TELEGRAM_BOT_TOKEN","") or os.getenv("BOT_TOKEN","")
    chat = os.getenv("TELEGRAM_CHAT_ID","") or os.getenv("CHAT_ID","")
    if not tok or not chat:
        print("ไม่มี TELEGRAM env - พิมพ์ใน Shell แทน")
        print(msg)
        return
    try:
        if photo:
            with open(photo,'rb') as f:
                requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto", data={"chat_id":chat,"caption":msg,"parse_mode":"HTML"}, files={"photo":("bt_all.png",f,"image/png")}, timeout=20)
        else:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id":chat,"text":msg,"parse_mode":"HTML"}, timeout=15)
    except Exception as e:
        print("send tele err", e)
        print(msg)

def main():
    f = DATA_DIR / "bt_results.json"
    if not f.exists():
        print("ยังไม่มี bt_results.json - รัน python backtest_G_POWER.py --days 30 ก่อน")
        return
    out = json.loads(f.read_text())
    print("="*60)
    print("BT V9 - จุดเข้า-ออก ทั้งหมด")
    print("="*60)
    for sym in ["btc","gold"]:
        if sym not in out: continue
        r = out[sym]
        print(f"\n{'BTC' if sym=='btc' else 'GOLD'} {r['days']} วัน: {r['trades']} ไม้ Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} PF {r['profit_factor']}")
        print(f"Avg Win ${r['avg_win']:+.2f} / Avg Loss ${r['avg_loss']:+.2f}")
        print("-"*60)
        for idx, tr in enumerate(r['trade_list'], 1):
            side = tr.get('side','?')
            entry = tr.get('entry',0)
            exit_p = tr.get('exit',0)
            wave = tr.get('wave','?')
            reason = tr.get('exit_reason','?')
            pnl = tr.get('pnl_usd',0)
            t = tr.get('time','')[:16]
            print(f"{idx:2d}. {side:5s} Wave {wave} เข้า {entry:,.1f} -> ออก {exit_p:,.1f} {reason} PnL ${pnl:+.2f} {t}")
        # ส่ง Telegram แบบแบ่งข้อความ กันยาวเกิน 4096
        lines = [f"📊 <b>BT V9 {'BTC' if sym=='btc' else 'GOLD'} ทั้งหมด {r['trades']} ไม้</b>",
                 f"Win {r['winrate_pct']}% PnL ${r['total_pnl']:+.2f} PF {r['profit_factor']} Avg Win ${r['avg_win']:+.2f} / Avg Loss ${r['avg_loss']:+.2f}",
                 ""]
        for idx, tr in enumerate(r['trade_list'], 1):
            lines.append(f"{idx}. {tr.get('side')} W{tr.get('wave','?')} {tr.get('entry',0):,.1f}->{tr.get('exit',0):,.1f} {tr.get('exit_reason')} ${tr.get('pnl_usd',0):+.2f}")
        msg = "\n".join(lines)
        # แบ่งทีละ 15 ไม้
        chunks = [lines[:3] + lines[3+i:3+i+15] for i in range(0, len(lines)-3, 15)]
        for ch in chunks:
            send_tele("\n".join(ch))
    # วาดกราฟจุดเข้า-ออก
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        # ใช้ klines cache ถ้ามี
        for sym in ["btc","gold"]:
            cache = DATA_DIR / f"klines_{sym}_15m.json"
            if not cache.exists():
                print(f"ไม่มี {cache} เลยวาดกราฟ {sym} ไม่ได้")
                continue
            rows = json.loads(cache.read_text())
            closes = [r[4] for r in rows]
            trades = out.get(sym,{}).get('trade_list',[])
            if not trades: continue
            W,H = 1080, 620
            img = Image.new("RGB",(W,H),"#0A0E1A")
            d = ImageDraw.Draw(img)
            try:
                f_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",28)
                f_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",18)
            except:
                f_big = ImageFont.load_default(); f_small = f_big
            d.text((20,15), f"{'BTC' if sym=='btc' else 'GOLD'} BT V9 - จุดเข้า-ออกทั้งหมด {len(trades)} ไม้  B=LONG S=SHORT X=ออก", font=f_big, fill="white")
            lo = min(closes + [t['entry'] for t in trades] + [t['exit'] for t in trades])
            hi = max(closes + [t['entry'] for t in trades] + [t['exit'] for t in trades])
            pad = (hi-lo)*0.08 or 1
            lo -= pad; hi += pad
            def py(v): return 520 - (v-lo)/(hi-lo)*400
            def px(i): return 40 + i*(1000/max(1,len(closes)-1))
            # เส้นราคา
            pts = [(px(i), py(v)) for i,v in enumerate(closes)]
            d.line(pts, fill="#54A0FF", width=2)
            # จุดเข้า-ออก: หา index ใกล้ราคาที่สุด
            for t in trades:
                # หาแท่งที่ราคาใกล้ entry ที่สุด
                try:
                    ei = min(range(len(closes)), key=lambda k: abs(closes[k]-t['entry']))
                    xi = min(range(len(closes)), key=lambda k: abs(closes[k]-t['exit']))
                except:
                    continue
                x_e, y_e = px(ei), py(t['entry'])
                col = "#2ED573" if t['side']=="LONG" else "#FF4757"
                lab = "B" if t['side']=="LONG" else "S"
                d.ellipse([x_e-14,y_e-14,x_e+14,y_e+14], fill=col, outline="white", width=2)
                d.text((x_e-5,y_e-8), lab, font=f_small, fill="white")
                x_x, y_x = px(xi), py(t['exit'])
                d.ellipse([x_x-10,y_x-10,x_x+10,y_x+10], fill="white", outline=col, width=2)
                d.text((x_x-5,y_x-8), "X", font=f_small, fill=col)
            d.text((20,560), "B/S = จุดเข้า  X = จุดออก  เส้นน้ำเงิน = ราคา 15m 30 วัน", font=f_small, fill="#8FA3C8")
            out_path = DATA_DIR / f"bt_all_chart_{sym}.png"
            img.save(out_path)
            print(f"วาดกราฟ {sym} แล้ว: {out_path}")
            send_tele(f"{'BTC' if sym=='btc' else 'GOLD'} จุดเข้า-ออกทั้งหมด {len(trades)} ไม้ - B/S=เข้า X=ออก", photo=str(out_path))
    except Exception as e:
        print("วาดกราฟ err", e)
        import traceback; traceback.print_exc()

if __name__ == "__main__":
    main()
