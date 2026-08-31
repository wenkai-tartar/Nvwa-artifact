重要：先运行：
```bash
./ns3 configure --build-profile=optimized --disable-tests --enable-examples --enable-modules "core;network;internet;applications;datacenter;point-to-point;nix-vector-routing"

./ns3 build
```

## 一键脚本

分别运行两类实验（按顺序串行，避免占满内存）：

```bash
bash src/datacenter/experiments/run_exp2_failure.sh
bash src/datacenter/experiments/run_exp3_nonminimal.sh
```

---

## 1) 最短路性能实验基线（NodeBfs / RuleBased）

### 1.1 Fattree

脚本：`src/datacenter/experiments/fattree_shortest_sweep.py`

运行前测试：
```bash
python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs \
  --only-k 8

python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --routing RuleBased \
  --only-k 8
```

实验命令：
```bash
python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs

python3 src/datacenter/experiments/fattree_shortest_sweep.py \
  --skip-build \
  --routing RuleBased
```

### 1.2 Dragonfly 最短路基线

脚本：`src/datacenter/experiments/dragonfly_shortest_sweep.py`

运行前测试：
```bash
python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs \
  --only-h 2

python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing RuleBased \
  --only-h 2
```

实验命令：
```bash
python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs

python3 src/datacenter/experiments/dragonfly_shortest_sweep.py \
  --skip-build \
  --routing RuleBased
```

### 1.3 3D Torus 最短路基线

脚本：`src/datacenter/experiments/torus_shortest_sweep.py`

运行前测试：
```bash
python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs \
  --only-d 2

python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing RuleBased \
  --only-d 2
```

实验命令：
```bash
python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing NodeBfs

python3 src/datacenter/experiments/torus_shortest_sweep.py \
  --skip-build \
  --routing RuleBased
```

## 2) Failure Fattree 性能实验（RuleBased）

脚本：`src/datacenter/experiments/fattree_failure_sweep.py`

实验规模：
- Fattree size：k = 8, 16, 24, 32, 40, 48, 56, 64
- failure rate：0.001, 0.01, 0.1

运行前测试：

```bash
python3 src/datacenter/experiments/fattree_failure_sweep.py \
  --skip-build \
  --build-profile optimized \
  --routing RuleBased \
  --only-k 8 \
  --only-fr 0.01 \
  --resume-policy skip_success
```

实验命令：
```bash
python3 src/datacenter/experiments/fattree_failure_sweep.py \
  --skip-build \
  --build-profile optimized \
  --routing RuleBased \
  --resume-policy skip_success
```

## 3) Non-minimal Policy Routing 性能实验（RuleBased）

脚本：  
- `src/datacenter/experiments/nonminimal_sweep_dragonfly_valiant.py`  
- `src/datacenter/experiments/nonminimal_sweep_dragonfly_ugal.py`  
- `src/datacenter/experiments/nonminimal_sweep_torus_detour.py`

实验规模：
1. Dragonfly Valiant：h = 2, 4, 6, 8, 10  
2. Dragonfly UGAL：h = 2, 4, 6, 8, 10  
3. 3D Torus Detour（1 阶段）：d = 5, 10, 15, 20  
4. 3D Torus Detour（2 阶段）：d = 5, 10, 15, 20  

配置说明：
- Dragonfly full-size：`a = 2p = 2h, g = a*h + 1`
- Torus：三维均为 d，节点数 `d*d*d`

运行前测试：
```bash
python3 src/datacenter/experiments/nonminimal_sweep_dragonfly_valiant.py --skip-build --only-h 2
python3 src/datacenter/experiments/nonminimal_sweep_dragonfly_ugal.py --skip-build --only-h 2
python3 src/datacenter/experiments/nonminimal_sweep_torus_detour.py --skip-build --only-d 5
```

实验命令：
```bash
python3 src/datacenter/experiments/nonminimal_sweep_dragonfly_valiant.py --skip-build
python3 src/datacenter/experiments/nonminimal_sweep_dragonfly_ugal.py --skip-build
python3 src/datacenter/experiments/nonminimal_sweep_torus_detour.py --skip-build
```
