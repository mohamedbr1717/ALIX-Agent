#!/bin/bash
# ALIX Phone Poller — يفحص طابور المكالمات/الرسائل على VPS عبر SSH.
#
# الاستخدام (Termux):
#   chmod +x phone_poller.sh
#   ./phone_poller.sh          # فحص مرة واحدة
#   ./phone_poller.sh --loop   # فحص دوري كل 60 ثانية
#
# المتطلبات:
#   - مفتاح SSH للسيرفر (ssh ubuntu@130.61.234.93 بدون كلمة مرور)
#   - Termux:API مثبت (pkg install termux-api)

VPS="ubuntu@130.61.234.93"
REMOTE_DIR="/home/ubuntu/ALIX-Agent/phone_queue"

check_requests() {
    # جلب الطلبات المعلقة
    local requests
    requests=$(ssh -o ConnectTimeout=10 "$VPS" \
        "ls $REMOTE_DIR/requests/*.json 2>/dev/null" 2>/dev/null)

    if [ -z "$requests" ]; then
        echo "لا توجد طلبات معلقة."
        return 0
    fi

    for req_file in $requests; do
        local rid
        rid=$(basename "$req_file" .json)

        # قراءة تفاصيل الطلب
        local content
        content=$(ssh -o ConnectTimeout=10 "$VPS" "cat $req_file" 2>/dev/null)

        local rtype number message
        rtype=$(echo "$content" | python3 -c "import json,sys; print(json.load(sys.stdin).get('type','?'))" 2>/dev/null)
        number=$(echo "$content" | python3 -c "import json,sys; print(json.load(sys.stdin).get('number','?'))" 2>/dev/null)
        message=$(echo "$content" | python3 -c "import json,sys; print(json.load(sys.stdin).get('message',''))" 2>/dev/null)

        echo ""
        echo "═══════════════════════════════════"
        echo "📞 طلب جديد (ID: $rid)"
        echo "النوع: $([ "$rtype" = "call" ] && echo "مكالمة هاتفية" || echo "رسالة SMS")"
        echo "الرقم: $number"
        [ -n "$message" ] && echo "النص: $message"
        echo "═══════════════════════════════════"

        # موافقة صريحة إلزامية
        read -p "توافق على التنفيذ؟ (نعم/لا): " answer

        local status detail
        if [ "$answer" = "نعم" ]; then
            if [ "$rtype" = "call" ]; then
                echo "جارٍ الاتصال بـ $number..."
                if termux-telephony-call "$number" 2>/dev/null; then
                    status="done"; detail="تم بدء المكالمة"
                else
                    status="failed"; detail="فشل بدء المكالمة"
                fi
            else
                echo "جارٍ إرسال الرسالة..."
                if termux-sms-send -n "$number" "$message" 2>/dev/null; then
                    status="done"; detail="تم إرسال الرسالة"
                else
                    status="failed"; detail="فشل إرسال الرسالة"
                fi
            fi
        else
            status="denied"; detail="رفض المستخدم"
            echo "تم الرفض."
        fi

        # إرجاع النتيجة للسيرفر
        ssh -o ConnectTimeout=10 "$VPS" \
            "cd /home/ubuntu/ALIX-Agent && python3 -c \"
from core.phone_queue import complete_request
complete_request('$rid', '$status', '''$detail''')
print('result recorded')
\"" 2>/dev/null

        echo "النتيجة: $status"
    done
}

if [ "$1" = "--loop" ]; then
    echo "وضع المراقبة الدورية (كل 60 ثانية). للإيقاف: Ctrl+C"
    while true; do
        check_requests
        sleep 60
    done
else
    check_requests
fi
