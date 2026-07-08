# W3 PCA 骞冲潎鑰虫妧鏈矾绾胯鏄?
> 闈㈠悜瀵硅薄锛氬悗缁帴鎵嬫湰椤圭洰鐨?AI 鎴栧伐绋嬪笀  
> 褰撳墠鏃ユ湡锛?026-07-08  
> 涓婃父杈撳叆锛歐2 remesh 杈撳嚭  
> 涓嬫父鐩爣锛歅CA 缁熻寤烘ā銆?5% 鏂瑰樊涓绘垚鍒嗛€夋嫨銆佸钩鍧囪€冲鍑?
## 1. 椤圭洰涓€鍙ヨ瘽鑳屾櫙

鏈」鐩殑鐩爣鏄妸涓嶅悓浜虹殑 3D 鑰虫湹妯″瀷杞崲鎴愬悓鎷撴墤銆佸悓鐐瑰簭銆佸悓鍖哄煙瀹氫箟鐨?remesh 琛ㄨ揪锛岀劧鍚庡湪杩欎釜缁熶竴琛ㄨ揪涓婂仛缁熻褰㈡€佸垎鏋愩€俉2 宸茬粡瀹炵幇锛氭牴鎹?landmark 鍒掑垎涓夎鍖哄煙锛屽皢灞€閮?3D patch 鍙傛暟鍖栧埌鏍囧噯 2D 涓夎鍩燂紝鍥哄畾閲囨牱鐐规暟閲忥紝鍐嶆槧灏勫洖 3D锛屽苟杈撳嚭 remesh 鐐广€侀潰銆丵C 鍜?landmark 鍑犱綍鐗瑰緛鍊笺€?
W3 鐨勪换鍔℃槸锛氬鎵€鏈夊悎鏍兼ā鍨嬭繘琛?PCA锛岄€夊彇绱瑙ｉ噴鏂瑰樊杈惧埌 75% 鐨勪富鎴愬垎锛岃绠楀钩鍧囧舰鐘讹紝骞朵粠缁熶竴 2D/template 琛ㄨ揪鏄犲皠鍥?3D锛屽緱鍒板钩鍧囪€炽€?
## 2. 褰撳墠浠ｇ爜鐘舵€?
鏍稿績鏂囦欢锛?
```text
ear_param/remesh.py
scripts/parameterize_ear_remesh.py
tests/test_remesh.py
docs/remesh_usage_w2.md
```

褰撳墠鎺ㄨ崘 W2 鍛戒护锛?
```powershell
python scripts/parameterize_ear_remesh.py --sample_id T001 --side L --mesh data/clean_mesh/T001_L.ply --landmarks data/landmarks/T001_L_landmarks.csv
```

W2 杈撳嚭鏂囦欢锛?
```text
output/parameterized_points/<sample>_<side>_remesh_points.csv
output/parameterized_points/<sample>_<side>_remesh_faces.csv
output/parameterized_points/<sample>_<side>_region_features.csv
output/parameterized_points/<sample>_<side>_remesh_qc.csv
output/remesh/<sample>_<side>/<region_id>_remesh.ply
```

褰撳墠鐪熷疄鏍锋湰绀轰緥锛?
```text
sample_id = T001
side = L
region_id = T001
resolution = 8
sample_point_count = 45
remesh_face_count = 64
status = PASS
```

## 3. W3 杈撳叆濂戠害

### 3.1 蹇呴』璇诲彇鐨勬枃浠?
瀵规瘡涓牱鏈紝璇诲彇锛?
```text
output/parameterized_points/<sample>_<side>_remesh_points.csv
output/parameterized_points/<sample>_<side>_remesh_faces.csv
output/parameterized_points/<sample>_<side>_remesh_qc.csv
```

鍙€夎鍙栵細

```text
output/parameterized_points/<sample>_<side>_region_features.csv
```

`region_features` 鐢ㄤ簬瑙ｉ噴 landmark 灏哄銆佽搴︺€侀潰绉樊寮傦紝涓嶆槸 PCA 褰㈡€佺煩闃电殑蹇呴渶杈撳叆銆?
### 3.2 points CSV 蹇呰瀛楁

`*_remesh_points.csv` 蹇呴』鍖呭惈锛?
```text
point_id
sample_id
side
region_id
region_name
region_point_id
lambda_a
lambda_b
lambda_c
u
v
source_face_index
is_unmapped
x
y
z
```

鍏抽敭鍚箟锛?
- `region_id`: 鍖哄煙缂栧彿銆?- `region_point_id`: 鍖哄煙鍐呴儴鍥哄畾鐐瑰簭锛屽繀椤昏法鏍锋湰涓€鑷淬€?- `lambda_a/lambda_b/lambda_c`: 鏍囧噯涓夎鍩熼噸蹇冨潗鏍囥€?- `u/v`: 鏍囧噯 2D 鍙傛暟鍧愭爣銆?- `x/y/z`: 璇ュ浐瀹氭ā鏉跨偣鏄犲皠鍥炴牱鏈?3D 鑰抽潰鐨勫潗鏍囥€?- `is_unmapped`: 濡傛灉涓?True锛屽垯璇ョ偣鏈垚鍔熶粠 2D 鏄犲皠鍥?3D锛屼笉鍙繘鍏?PCA銆?
### 3.3 faces CSV 蹇呰瀛楁

`*_remesh_faces.csv` 蹇呴』鍖呭惈锛?
```text
sample_id
side
region_id
region_name
face_id
local_v0
local_v1
local_v2
global_v0
global_v1
global_v2
```

鍏抽敭鍚箟锛?
- `local_v0/local_v1/local_v2`: 鍗曚釜 region 鍐呴儴鐨勫浐瀹氶潰鐗囬《鐐圭储寮曘€?- `global_v0/global_v1/global_v2`: 灏嗗涓?region 鎷兼帴涓轰竴涓牱鏈骇 mesh 鏃朵娇鐢ㄧ殑鍏ㄥ眬椤剁偣绱㈠紩銆?
### 3.4 QC 蹇呰瀛楁

`*_remesh_qc.csv` 蹇呴』鍖呭惈锛?
```text
sample_id
side
region_id
sample_point_count
expected_point_count
remesh_face_count
unmapped_count
degenerate_faces
mesh_exported
status
```

W3 鍙厑璁镐娇鐢ㄦ弧瓒充互涓嬫潯浠剁殑 region锛?
```text
status == "PASS"
sample_point_count == expected_point_count
unmapped_count == 0
degenerate_faces == 0
```

濡傛灉鏌愪釜鏍锋湰鐨勬煇涓?`region_id` 涓嶆弧瓒虫潯浠讹紝鍒欒鏍锋湰鍦ㄨ region 鐨?PCA 涓繀椤诲墧闄ゃ€備笉瑕佺敤 NaN 濉厖鍚庣‖鍋?PCA銆?
## 4. W3 鏁版嵁缁勭粐鏂瑰紡

### 4.1 鎺ㄨ崘鍏堟寜 region 鍋?PCA

涓嶈涓€寮€濮嬪氨鎶婃墍鏈夊尯鍩熸嫾鎴愭暣鑰?PCA銆傛帹鑽愭祦绋嬶細

1. 瀵规瘡涓?`region_id` 鐙珛鏀堕泦鍚堟牸鏍锋湰銆?2. 姣忎釜鏍锋湰鍦ㄨ region 鍐呭舰鎴愪竴涓悜閲忋€?3. 瀵硅 region 鐨勬牱鏈煩闃靛仛 PCA銆?4. 寰楀埌璇?region 鐨勫钩鍧?patch銆?5. 鏈€鍚庢妸鎵€鏈?region 骞冲潎 patch 鎸夊浐瀹?faces 鎷兼帴涓哄钩鍧囪€炽€?
鐞嗙敱锛?
- 褰撳墠 W2 浠ヤ笁瑙?region 涓哄熀鏈崟浣嶃€?- 姣忎釜 region 鐨?QC 鐘舵€佸彲鑳戒笉鍚屻€?- 鎸?region PCA 鏇村鏄撳畾浣嶅け璐ュ尯鍩熴€?- 瀵归綈鏂瑰紡鐢?`region_point_id` 淇濊瘉銆?
### 4.2 鍗曚釜 region 鐨勭煩闃靛舰鐘?
璁撅細

```text
N = 鍚堟牸鏍锋湰鏁?P = 璇?region 鐨勫浐瀹氶噰鏍风偣鏁?```

渚嬪 `resolution=8` 鏃讹細

```text
P = 45
```

姣忎釜鏍锋湰鐨?3D 鍧愭爣鐭╅樀锛?
```text
points_3d.shape == (P, 3)
```

灞曞钩涓?PCA 杈撳叆鍚戦噺锛?
```text
shape_vector = [x0,y0,z0, x1,y1,z1, ..., x(P-1),y(P-1),z(P-1)]
shape_vector.shape == (P * 3,)
```

鎵€鏈夋牱鏈爢鍙狅細

```text
X.shape == (N, P * 3)
```

瀵?`X` 鍋?PCA銆?
### 4.3 鐐瑰簭鎺掑簭瑙勫垯

璇诲彇 points 鍚庡繀椤绘帓搴忥細

```python
df = df.sort_values(["region_id", "region_point_id"])
```

瀵逛簬鍗?region锛?
```python
region_df = region_df.sort_values("region_point_id")
```

绂佹鎸?CSV 鍘熷琛岄『搴忕洸鐩俊浠伙紝铏界劧褰撳墠鑴氭湰鎸夊浐瀹氶『搴忚緭鍑猴紝浣?W3 搴旀樉寮忔帓搴忎互闃插悗缁枃浠舵嫾鎺ユ垨浜哄伐缂栬緫鐮村潖椤哄簭銆?
## 5. PCA 绠楁硶璺嚎

### 5.1 鏍囧噯 PCA

杈撳叆锛?
```text
X: shape (N, D)
D = P * 3
```

姝ラ锛?
1. 璁＄畻鍧囧€煎悜閲忥細

```text
mean_vector = X.mean(axis=0)
```

2. 涓績鍖栵細

```text
X_centered = X - mean_vector
```

3. 鍋?PCA锛?
鎺ㄨ崘浣跨敤 `sklearn.decomposition.PCA`銆傚鏋滀笉鎯虫柊澧炰緷璧栵紝鍙敤 `numpy.linalg.svd`銆傚綋鍓?`requirements.txt` 娌℃湁 `scikit-learn`锛屼负浜嗘渶灏忎緷璧栵紝寤鸿浼樺厛瀹炵幇 SVD 鐗堟湰銆?
SVD 鐗堟湰锛?
```python
U, S, Vt = np.linalg.svd(X_centered, full_matrices=False)
explained_variance = (S ** 2) / (N - 1)
explained_variance_ratio = explained_variance / explained_variance.sum()
components = Vt
```

4. 閫夋嫨绱瑙ｉ噴鏂瑰樊杈惧埌 75% 鐨勪富鎴愬垎鏁帮細

```python
cumulative = np.cumsum(explained_variance_ratio)
n_components_75 = int(np.searchsorted(cumulative, 0.75) + 1)
```

5. 杈撳嚭锛?
```text
mean_vector
components[:n_components_75]
explained_variance[:n_components_75]
explained_variance_ratio[:n_components_75]
cumulative[:n_components_75]
```

### 5.2 鏍锋湰鏁伴檺鍒?
PCA 鑷冲皯闇€瑕?2 涓悎鏍兼牱鏈細

```text
N >= 2
```

濡傛灉 `N < 2`锛?
- 涓嶈绠?PCA銆?- 鍙互杈撳嚭璇?region 鐨?`mean_vector`銆?- QC 鏍囪涓?`INSUFFICIENT_SAMPLES`銆?
褰撳墠浠撳簱鍙湁涓€涓湡瀹炴牱鏈?`T001_L`锛屾墍浠ョ幇鍦ㄥ彧鑳介獙璇?W3 杈撳叆缁勭粐銆佸潎鍊奸噸寤哄拰鏂囦欢杈撳嚭锛屼笉鑳藉畬鎴愮湡姝?PCA銆?
## 6. 骞冲潎鑰崇敓鎴愯矾绾?
### 6.1 骞冲潎 patch

瀵规瘡涓?region锛?
```python
mean_points = mean_vector.reshape(P, 3)
```

faces 浣跨敤璇?region 鐨勫浐瀹?faces锛?
```python
faces = faces_df[["local_v0", "local_v1", "local_v2"]].to_numpy(dtype=int)
```

鐢熸垚鍗?region 骞冲潎 patch锛?
```python
trimesh.Trimesh(vertices=mean_points, faces=faces, process=False)
```

### 6.2 骞冲潎鑰虫暣浣?mesh

濡傛灉澶氫釜 region 鐩存帴鎷兼帴锛?
1. 瀵规瘡涓?region 鍙?`mean_points`銆?2. 绱姞椤剁偣鍋忕Щ閲忋€?3. 灏?region faces 鍔犱笂 offset銆?4. concatenate 鎴愪竴涓?mesh銆?
娉ㄦ剰锛氱浉閭?region 鐨勮竟鐣岀偣鍙兘閲嶅銆傜涓€鐗堝彲浠ユ帴鍙楅噸澶嶈竟鐣岀偣锛屽洜涓?W2 鐨勭粺璁″榻愭牳蹇冩槸鍥哄畾妯℃澘鐐瑰簭锛屼笉鏄棤缂?watertight mesh銆傝嫢鍚庣画闇€瑕佺敓浜х骇骞冲潎鑰筹紝鍐嶅仛杈圭晫鐐?merge銆?
### 6.3 鈥滀粠 2D 骞抽潰鏄犲皠鍥?3D鈥濈殑瑙ｉ噴

W2 宸茬粡涓烘瘡涓牱鏈缓绔嬩簡鏍囧噯 2D 妯℃澘鐐瑰拰 3D 鏇查潰鐐圭殑瀵瑰簲鍏崇郴锛?
```text
(region_id, region_point_id, u, v, lambda_a, lambda_b, lambda_c) -> (x, y, z)
```

W3 鐨勫钩鍧囪€充笉鏄噸鏂板湪鍘熷 mesh 涓婃彃鍊硷紝鑰屾槸鍦ㄥ浐瀹?2D/template 瀵瑰簲鐐逛笂瀵规墍鏈夋牱鏈殑 3D 鍧愭爣姹傚潎鍊硷細

```text
mean_3d(region_id, region_point_id) = average over samples of 3D coordinate at same 2D/template point
```

鍥犳骞冲潎鑰冲ぉ鐒朵繚鐣欙細

- 涓?W2 鐩稿悓鐨?2D 鐐瑰簭銆?- 涓?W2 鐩稿悓鐨?remesh faces銆?- 姣忎釜骞冲潎鐐瑰搴斾竴涓浐瀹氱殑 `(u, v)` 鍜岄噸蹇冨潗鏍囥€?
## 7. 寤鸿鏂板鏂囦欢

### 7.1 鏍稿績妯″潡

寤鸿鏂板锛?
```text
ear_param/pca_average.py
```

鑱岃矗锛?
- 璇诲彇 W2 remesh 杈撳嚭銆?- 鎸?region 鑱氬悎鍚堟牸鏍锋湰銆?- 鏋勫缓 PCA 鐭╅樀銆?- 鎵ц SVD PCA銆?- 鐢熸垚骞冲潎 patch 鍜屽钩鍧囪€?mesh銆?
寤鸿鍑芥暟锛?
```python
def discover_remesh_outputs(points_dir: Path) -> list[Path]:
    ...

def load_sample_remesh(sample_tag: str, points_dir: Path) -> dict:
    ...

def filter_pass_regions(qc_df: pd.DataFrame) -> set[str]:
    ...

def build_region_matrix(samples: list[SampleRemesh], region_id: str) -> RegionMatrix:
    ...

def run_pca_75(matrix: np.ndarray) -> PCAResult:
    ...

def build_mean_region_mesh(mean_points: np.ndarray, faces: np.ndarray) -> trimesh.Trimesh:
    ...

def build_mean_ear_mesh(region_meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    ...
```

### 7.2 鍛戒护琛岃剼鏈?
寤鸿鏂板锛?
```text
scripts/build_average_ear.py
```

鎺ㄨ崘鍛戒护锛?
```powershell
python scripts/build_average_ear.py --points_dir output/parameterized_points --out_dir output/pca_average
```

### 7.3 杈撳嚭鐩綍

寤鸿杈撳嚭锛?
```text
output/pca_average/pca_summary.csv
output/pca_average/<region_id>_mean_points.csv
output/pca_average/<region_id>_pca_components.csv
output/pca_average/<region_id>_explained_variance.csv
output/pca_average/<region_id>_mean_patch.ply
output/pca_average/average_ear.ply
output/pca_average/average_ear_points.csv
output/pca_average/average_ear_faces.csv
```

## 8. 杈撳嚭鏂囦欢瀹氫箟

### 8.1 `pca_summary.csv`

瀛楁锛?
```text
region_id
n_samples
n_points
n_dimensions
n_components_75
explained_variance_75
status
message
```

鍏朵腑锛?
- `explained_variance_75`: 閫夋嫨 `n_components_75` 鍚庣殑绱瑙ｉ噴鏂瑰樊锛屽簲 >= 0.75銆?- `status`: `PASS` / `INSUFFICIENT_SAMPLES` / `FAIL`銆?
### 8.2 `<region_id>_mean_points.csv`

瀛楁锛?
```text
region_id
region_point_id
lambda_a
lambda_b
lambda_c
u
v
x
y
z
```

瑕佹眰锛?
- `region_point_id` 蹇呴』杩炵画銆?- `x/y/z` 涓嶅厑璁告湁 NaN/Inf銆?
### 8.3 `<region_id>_pca_components.csv`

闀胯〃鏍煎紡鏇撮€傚悎妫€鏌ワ細

```text
region_id
component_id
dimension_id
coordinate
point_id
axis
value
```

鍏朵腑锛?
- `axis` 鏄?`x/y/z`銆?- `dimension_id = point_id * 3 + axis_index`銆?
### 8.4 `average_ear.ply`

骞冲潎鑰?mesh锛?
- vertices 鏉ヨ嚜鎵€鏈?region 鐨?mean points銆?- faces 鏉ヨ嚜鎵€鏈?region 鐨?fixed template faces锛屾寜 region 鍋忕Щ鍚庢嫾鎺ャ€?
## 9. 娴嬭瘯璁″垝

### 9.1 鍗曞厓娴嬭瘯

寤鸿鏂板锛?
```text
tests/test_pca_average.py
```

蹇呴』瑕嗙洊锛?
1. `run_pca_75` 鑳芥纭€夋嫨绱瑙ｉ噴鏂瑰樊 >= 75% 鐨勪富鎴愬垎鏁般€?2. 鍗?region 鐨?points CSV 鑳芥瀯閫犳垚姝ｇ‘褰㈢姸鐭╅樀銆?3. region 鍐呯偣搴忔寜 `region_point_id` 鎺掑簭锛岃€屼笉鏄寜鍘熸枃浠惰椤哄簭銆?4. QC 涓嶅悎鏍兼牱鏈鍓旈櫎銆?5. 鍙湁 1 涓悎鏍兼牱鏈椂杩斿洖 `INSUFFICIENT_SAMPLES`锛屼笉鍋囪瀹屾垚 PCA銆?6. mean vector reshape 鍚庡緱鍒?`(P, 3)`銆?7. 骞冲潎 patch mesh 浣跨敤鍥哄畾 template faces銆?
### 9.2 鏈€灏忔祴璇曟暟鎹?
娴嬭瘯涓笉渚濊禆鐪熷疄 T001 澶ф枃浠躲€傛瀯閫犱袱涓皬鏍锋湰锛?
```text
S001_R: 3 points
S002_R: 3 points
faces: 1 triangle
```

渚嬪锛?
```python
S001 = [[0,0,0], [1,0,0], [0,1,0]]
S002 = [[0,0,1], [1,0,1], [0,1,1]]
mean = [[0,0,0.5], [1,0,0.5], [0,1,0.5]]
```

杩欐牱鍙互娓呮楠岃瘉骞冲潎鍊笺€?
### 9.3 闆嗘垚娴嬭瘯

鍦ㄥ綋鍓嶇湡瀹?T001 鏁版嵁涓婏紝闆嗘垚娴嬭瘯鍙兘楠岃瘉锛?
- 鑳藉彂鐜?W2 杈撳嚭銆?- 鑳借鍙?points/faces/qc銆?- 鑳界敓鎴?mean points銆?- 鍥犳牱鏈暟涓嶈冻锛孭CA summary 姝ｇ‘鏍囪 `INSUFFICIENT_SAMPLES`銆?
涓嶈鐢ㄥ崟鏍锋湰 T001 澹扮О瀹屾垚 PCA銆?
## 10. 浜や粯鏍囧噯

W3 绗竴鐗堝畬鎴愭椂锛屽繀椤绘弧瓒筹細

1. 鏈?`ear_param/pca_average.py`銆?2. 鏈?`scripts/build_average_ear.py`銆?3. 鏈?`tests/test_pca_average.py`銆?4. `python -m pytest -q` 鍏ㄩ儴閫氳繃銆?5. 瀵瑰崟鏍锋湰 T001 鑳界敓鎴?`pca_summary.csv`锛屽苟姝ｇ‘鎻愮ず鏍锋湰涓嶈冻銆?6. 瀵规祴璇曠敤鍙屾牱鏈暟鎹兘鐢熸垚骞冲潎 patch锛屼笖鍧囧€煎潗鏍囧彲楠岃瘉銆?7. 鏂囨。璇存槑娓呮鈥?5% 鏂瑰樊涓绘垚鍒嗏€濆浣曢€夋嫨銆?8. 涓嶄慨鏀?W2 remesh 杈撳嚭鏍煎紡锛岄櫎闈炲悓姝ユ洿鏂版湰鏂囦欢鍜?README銆?
## 11. 甯歌閿欒涓庨槻鎶?
### 閿欒 1锛氭妸涓嶅悎鏍?region 濉?NaN 鍚庡仛 PCA

绂佹銆傚繀椤诲厛鎸?QC 鍓旈櫎涓嶅悎鏍兼牱鏈€?
### 閿欒 2锛氬繕璁版寜 `region_point_id` 鎺掑簭

浼氬鑷翠笉鍚屾牱鏈殑鐐归敊浣嶏紝PCA 缁撴灉鏃犳剰涔夈€傚繀椤绘樉寮忔帓搴忋€?
### 閿欒 3锛氭妸鍗曟牱鏈?PCA 褰撲綔鏈夋晥缁撴灉

鍗曟牱鏈彧鑳藉緱鍒板潎鍊硷紝涓嶈兘寰楀埌鍙潬涓绘垚鍒嗐€傚繀椤绘爣璁?`INSUFFICIENT_SAMPLES`銆?
### 閿欒 4锛氶噸鏂扮敓鎴?faces

W3 涓嶅簲閲嶆柊 remesh 鎴栭噸鏂?triangulate銆俧aces 蹇呴』鏉ヨ嚜 W2 鐨?`*_remesh_faces.csv`銆?
### 閿欒 5锛氭贩鐢ㄤ笉鍚?region 鐨勭偣

绗竴鐗堝繀椤绘寜 region 鐙珛 PCA銆傛暣鑰?PCA 鍙互鍚庣画鍔狅紝浣嗕笉鏄涓€鐗堝繀闇€銆?
## 12. 鎺ㄨ崘瀹炵幇椤哄簭

1. 鍐?`tests/test_pca_average.py` 鐨勬渶灏忓弻鏍锋湰鍧囧€兼祴璇曘€?2. 瀹炵幇 CSV 璇诲彇鍜?QC 杩囨护銆?3. 瀹炵幇 region matrix 鏋勫缓銆?4. 瀹炵幇 SVD PCA 鍜?75% 鏂瑰樊閫夋嫨銆?5. 瀹炵幇 mean patch mesh 瀵煎嚭銆?6. 瀹炵幇 CLI銆?7. 鐢?T001 鍗曟牱鏈窇閫氭牱鏈笉瓒冲垎鏀€?8. 鏇存柊 README銆?
## 13. 鍜?W2 鐨勫叧绯?
W2 杈撳嚭鐨勬槸璺ㄦ牱鏈彲瀵归綈鐨勫悓鎷撴墤灞€閮?remesh銆俉3 涓嶅啀澶勭悊鍘熷楂樺瘑搴?mesh锛屼篃涓嶅啀閲嶆柊鎵?landmark锛屼笉鍐嶉噸鏂板仛 harmonic parameterization銆?
W3 鐨勫敮涓€鍙俊杈撳叆鏄?W2 鐨勫悎鏍艰緭鍑猴細

```text
*_remesh_points.csv
*_remesh_faces.csv
*_remesh_qc.csv
```

鍙杩欎簺鏂囦欢鐨?schema 绋冲畾锛學3 灏卞彲浠ョ嫭绔嬪紑鍙戙€佹祴璇曞拰浜や粯銆?

