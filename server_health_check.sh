#!/bin/bash
# ============================================================================
# yikeUIAuto 服务器一键巡检脚本
# 用途：一次跑完 5 项日常巡检，用 [OK]/[WARN]/[FAIL] 标记异常。
# 用法：把本文件保存为脚本，通过 TAT 技能在服务器执行即可（无需参数）。
#       例：cat server_health_check.sh | tat_exec.py
# 说明：纯文本标记，无 ANSI 颜色（TAT 回传可能strip颜色），便于直接看结果。
# ============================================================================

echo "=================================================================="
echo " yikeUIAuto 服务器巡检  $(date '+%F %T %Z')"
echo "=================================================================="

# ---------- 1. 服务存活 ----------
echo ""
echo "【1/5 服务存活】"
fail=0
for svc in yikeui mysqld nginx; do
  st=$(systemctl is-active "$svc" 2>/dev/null)
  if [ "$st" = "active" ]; then
    echo "  [OK]   $svc : $st"
  else
    echo "  [FAIL] $svc : $st   << 服务未正常运行，需处置"
    fail=$((fail+1))
  fi
done

# ---------- 2. 进程健康 / 残留 worker ----------
echo ""
echo "【2/5 进程健康 / 残留 worker】"
lines=$(ps -eo pid,etime,cmd | grep "gunicorn yikeui.wsgi" | grep -v grep)
count=$(echo "$lines" | grep -c "gunicorn")
distinct=$(echo "$lines" | awk 'NF{print $2}' | sort -u | wc -l)
if [ "$count" -eq 0 ]; then
  echo "  [FAIL] 未发现任何 gunicorn 进程  << 服务未起"
  fail=$((fail+1))
else
  echo "$lines" | awk '{printf "  pid=%-7s etime=%-12s\n", $1, $2}'
  if [ "$count" -eq 3 ] && [ "$distinct" -le 2 ]; then
    echo "  [OK]   进程数=$count, etime分布=$distinct (干净实例: 1 master + 2 worker)"
  else
    echo "  [WARN] 进程数=$count, etime分布=$distinct  << 可能有残留旧 worker，建议: systemctl restart yikeui"
  fi
fi

# ---------- 3. 错误日志 ----------
echo ""
echo "【3/5 错误日志】"
if journalctl -u yikeui.service -p err --since today --no-pager 2>/dev/null | grep -q "No entries"; then
  echo "  [OK]   今日无 error 级日志"
else
  echo "  [FAIL] 今日存在 error 级日志："
  journalctl -u yikeui.service -p err --since today --no-pager 2>/dev/null | tail -10 | sed 's/^/    /'
  fail=$((fail+1))
fi
# 额外扫一遍“全部日志”里的失败/异常字样（含低危，如 4031 MySQL 空闲断连）
hits=$(journalctl -u yikeui.service --since today --no-pager 2>/dev/null | grep -ciE "失败|error|traceback|exception|disconnected")
if [ "$hits" -gt 0 ]; then
  echo "  [WARN] 今日全部日志含 $hits 处失败/异常字样（含低危），建议人工过目："
  journalctl -u yikeui.service --since today --no-pager 2>/dev/null | grep -iE "失败|error|traceback|exception|disconnected" | tail -5 | sed 's/^/    /'
fi

# ---------- 4. 资源（磁盘/内存/swap） ----------
echo ""
echo "【4/5 资源】"
diskuse=$(df -h / | awk 'NR==2 {gsub("%",""); print $5}')
echo "  磁盘使用: ${diskuse}%"
if [ "$diskuse" -ge 80 ]; then
  echo "  [WARN] 磁盘 >=80%，建议清理报告/截图/日志"
else
  echo "  [OK]   磁盘 <80%"
fi
memavail=$(free -m | awk '/Mem:/ {print $7}')
echo "  内存可用: ${memavail}MB"
if [ "$memavail" -lt 200 ]; then
  echo "  [WARN] 可用内存 <200MB，有 OOM 风险（必要时把 --workers 降到 1）"
  fail=$((fail+1))
else
  echo "  [OK]   内存充足"
fi
swaptot=$(free -m | awk '/Swap:/ {print $2}'); swapuse=$(free -m | awk '/Swap:/ {print $3}')
echo "  swap: ${swapuse}/${swaptot}MB"

# ---------- 5. 页面冒烟 ----------
echo ""
echo "【5/5 页面冒烟】"
for p in / /cases/ /runs/ /admin/; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "http://127.0.0.1$p")
  # 本站点有登录保护：未登录访问会被重定向(301/302)或要求鉴权(401/403)，均属“服务可达”的正常表现；
  # 只有连接失败(000)或服务错误(5xx)才算真故障。
  case "$code" in
    200|301|302|401|403) echo "  [OK]   $p -> $code  (可达；受保护页跳转/鉴权属正常)";;
    000|500|502|503|504) echo "  [FAIL] $p -> $code   << 服务异常，需排查"; fail=$((fail+1));;
    *) echo "  [WARN] $p -> $code   << 非预期状态码，请确认";;
  esac
done

# ---------- 汇总 ----------
echo ""
echo "=================================================================="
if [ "$fail" -eq 0 ]; then
  echo " 巡检通过：未发现 FAIL 项（WARN 项请按需关注）"
else
  echo " 巡检发现 $fail 个 FAIL 项，请逐项处置"
fi
echo "=================================================================="
