import pandas as pd
import matplotlib.pyplot as plt

# Data (DECLARATIE, AN, VALOARE)
data = [
 ("D112",2020,33144245), ("D112",2021,42161299), ("D112",2022,55446002),
 ("D112",2023,70064847), ("D112",2024,78614782), ("D112",2025,41891341),
 ("D205",2020,6626765),  ("D205",2021,12234906), ("D205",2022,42060273),
 ("D205",2023,21720723), ("D205",2024,40100216), ("D205",2025,0),
 ("D208",2020,176130),   ("D208",2021,516433),   ("D208",2022,914965),
 ("D208",2023,1866181),  ("D208",2024,819931),   ("D208",2025,938187),
 ("D209",2020,0),        ("D209",2021,0),        ("D209",2022,0),
 ("D209",2023,0),        ("D209",2024,1360),     ("D209",2025,0),
 ("D224",2020,8340833),  ("D224",2021,10559396), ("D224",2022,12871285),
 ("D224",2023,13427795), ("D224",2024,14073471), ("D224",2025,10282837),
 ("DUF",2020,7597524),   ("DUF",2021,27488343),  ("DUF",2022,23541978),
 ("DUF",2023,28490147),  ("DUF",2024,32022403),  ("DUF",2025,0),
 ("RIF",2020,0),         ("RIF",2021,163808),    ("RIF",2022,943470),
 ("RIF",2023,0),         ("RIF",2024,0),         ("RIF",2025,0),
]

df = pd.DataFrame(data, columns=["DECLARATIE","AN","VALOARE"]).sort_values(["DECLARATIE","AN"])

years = sorted(df["AN"].unique().tolist())
decls = df["DECLARATIE"].unique().tolist()

# Flatten in the order: D112(2020..2025), D205(2020..2025), ...
ordered_rows = []
for decl in decls:
    sub = df[df["DECLARATIE"] == decl].set_index("AN").reindex(years).reset_index()
    sub["DECLARATIE"] = decl
    ordered_rows.append(sub)
ordered = pd.concat(ordered_rows, ignore_index=True)

# Build x positions with small gaps between declaration blocks
gap = 1.5
x_positions, x_labels, group_centers = [], [], []
pos = 0.0

for decl in decls:
    start_pos = pos
    for y in years:
        x_positions.append(pos)
        x_labels.append(str(y))
        pos += 1.0
    end_pos = pos - 1.0
    group_centers.append(((start_pos + end_pos) / 2.0, decl))
    pos += gap

vals = ordered["VALOARE"].tolist()

plt.figure(figsize=(14,5))
ax = plt.gca()
ax.bar(x_positions, vals)
ax.set_ylabel("Valoare (RON)")
ax.set_xlabel("An (grupat pe declarație)")
ax.grid(True, axis="y", linestyle="--", linewidth=0.5, alpha=0.6)

ax.set_xticks(x_positions)
ax.set_xticklabels(x_labels)

# Add declaration labels beneath x-axis
ymin, ymax = ax.get_ylim()
for center, decl in group_centers:
    ax.text(center, ymin - (ymax - ymin)*0.08, decl, ha="center", va="top", fontsize=10, clip_on=False)

plt.tight_layout()
plt.savefig("declaratii_bars_continuous.png", dpi=200, bbox_inches="tight")
plt.show()
