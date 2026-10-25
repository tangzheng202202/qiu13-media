import json, os, sys, time, subprocess, shutil, requests
model_key, task = sys.argv[1], sys.argv[2]
run_id = sys.argv[3] if len(sys.argv)>3 else ""
MAXSTEPS=int(os.environ.get("MAXSTEPS","30"))
CFG = {"deepseek": ("https://api.deepseek.com/chat/completions", "DEEPSEEK_API_KEY", "deepseek-flash"),
       "kimi": ("https://api.moonshot.cn/v1/chat/completions", "MOONSHOT_API_KEY", "kimi-k3.1-pro")}
url, env, model = CFG[model_key]
base = os.path.dirname(os.path.abspath(__file__))
work = f"{base}/runs/{model_key}/{task}{run_id}"
shutil.rmtree(work, ignore_errors=True)
shutil.copytree(f"{base}/tasks/{task}", work, ignore=shutil.ignore_patterns("hidden_test.py"))
prompt = open(f"{base}/prompts/{task}.md").read()
SYSTEM = "You are a coding agent working in a repository at the current working directory. Use the tools to inspect, edit and run code (python3 and pytest are available on PATH). When finished, reply with a short summary and no tool call."
tools = [
 {"type":"function","function":{"name":"bash","description":"Run a shell command in the repo directory. Returns stdout+stderr (truncated to 8000 chars).","parameters":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}},
 {"type":"function","function":{"name":"write_file","description":"Create or overwrite a file (path relative to repo).","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
 {"type":"function","function":{"name":"read_file","description":"Read a file (path relative to repo).","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}}]
envp = dict(os.environ, PATH=f"{base}/.venv/bin:"+os.environ["PATH"])
for k in ("DEEPSEEK_API_KEY","MOONSHOT_API_KEY","GLM_API_KEY","MINIMAX_API_KEY"): envp.pop(k, None)
def run_tool(name, a):
    try:
        if name=="bash":
            r = subprocess.run(a["command"], shell=True, cwd=work, env=envp, capture_output=True, text=True, timeout=120)
            return (r.stdout+r.stderr)[-8000:] + f"\n[exit {r.returncode}]"
        p = os.path.join(work, a["path"])
        if name=="write_file":
            os.makedirs(os.path.dirname(p), exist_ok=True); open(p,"w").write(a["content"]); return "ok"
        return open(p).read()[:8000]
    except Exception as e: return f"error: {e}"
msgs=[{"role":"system","content":SYSTEM},{"role":"user","content":prompt}]
usage={"prompt":0,"completion":0,"cached":0,"calls":0}; log=[]
t0=time.time()
for step in range(MAXSTEPS):
    body={"model":model,"messages":msgs,"tools":tools,"max_tokens":32000}
    for attempt in range(120):
        ts=time.time()
        try:
            r=requests.post(url,headers={"Authorization":"Bearer "+os.environ[env]},json=body,timeout=600)
            if r.status_code==200: break
            print("HTTP",r.status_code,r.text[:200],file=sys.stderr)
        except Exception as e: print("ERR",e,file=sys.stderr)
        usage["retry_wait"]=usage.get("retry_wait",0)+(time.time()-ts)+30; time.sleep(30)
    r.raise_for_status(); j=r.json(); u=j.get("usage",{})
    usage["calls"]+=1; usage["prompt"]+=u.get("prompt_tokens",0); usage["completion"]+=u.get("completion_tokens",0)
    usage["cached"]+=u.get("prompt_cache_hit_tokens", u.get("cached_tokens", (u.get("prompt_tokens_details") or {}).get("cached_tokens",0)) or 0)
    log.append({"usage":u}); json.dump(usage,open(f"{work}/../{task}{run_id}.partial_usage.json","w"))
    m=j["choices"][0]["message"]
    am={"role":"assistant","content":m.get("content") or ""}
    if m.get("reasoning_content"): am["reasoning_content"]=m["reasoning_content"]
    if m.get("tool_calls"): am["tool_calls"]=m["tool_calls"]
    msgs.append(am)
    if not m.get("tool_calls"): break
    for tc in m["tool_calls"]:
        try: a=json.loads(tc["function"]["arguments"])
        except Exception: a={}
        out=run_tool(tc["function"]["name"],a)
        msgs.append({"role":"tool","tool_call_id":tc["id"],"content":out})
wall=time.time()-t0
shutil.copy(f"{base}/tasks/{task}/hidden_test.py", work) if os.path.exists(f"{base}/tasks/{task}/hidden_test.py") else None
tf = "hidden_test.py" if task!="t1_bugfix" else "test_inventory.py"
if task=="t1_bugfix": shutil.copy(f"{base}/tasks/{task}/test_inventory.py", work)  # restore original tests
try: tr=subprocess.run([f"{base}/.venv/bin/pytest","-q","-p","no:cacheprovider",tf],cwd=work,capture_output=True,text=True,timeout=300)
except subprocess.TimeoutExpired: tr=subprocess.CompletedProcess([],1,"TIMEOUT\n","")
import re
npass=int((re.search(r"(\d+) passed",tr.stdout) or [0,0])[1]); nfail=int((re.search(r"(\d+) failed",tr.stdout) or [0,0])[1])+int((re.search(r"(\d+) error",tr.stdout) or [0,0])[1])
open(f"{work}/../{task}{run_id}.hidden_tests.txt","w").write(tr.stdout[-6000:])
res={"model":model,"task":task,"wall_s":round(wall,1),"steps":usage["calls"],**usage,"tests":tr.stdout.strip().splitlines()[-1],"pass":tr.returncode==0,"score":f"{npass}/{npass+nfail}","raw_last_usage":u}
json.dump(msgs,open(f"{work}/../{task}{run_id}.transcript.json","w"),ensure_ascii=False,indent=1)
json.dump(res,open(f"{work}/../{task}{run_id}.result.json","w"),indent=1); print(json.dumps(res))
