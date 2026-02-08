import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter

# 1. Create the dataset
data = {
    'DECLARATIE': ['D112'] * 6 + ['D205'] * 6 + ['D208'] * 6 + ['D209'] * 6 + ['D224'] * 6 + ['DUF'] * 6 + ['RIF'] * 6,
    'AN': [2020, 2021, 2022, 2023, 2024, 2025] * 7,
    'VALOARE': [
        33144245, 42161299, 55446002, 70064847, 78614782, 41891341,  # D112
        6626765, 12234906, 42060273, 21720723, 40100216, 0,  # D205
        176130, 516433, 914965, 1866181, 819931, 938187,  # D208
        0, 0, 0, 0, 1360, 0,  # D209
        8340833, 10559396, 12871285, 13427795, 14073471, 10282837,  # D224
        7597524, 27488343, 23541978, 28490147, 32022403, 0,  # DUF
        0, 163808, 943470, 0, 0, 0  # RIF
    ]
}

df = pd.DataFrame(data)

# 2. Define Groups and Colors
top_row_decls = ['D112', 'D205', 'D224', 'DUF']
bottom_row_decls = ['D208', 'RIF', 'D209']
all_decls = top_row_decls + bottom_row_decls

# Palette
palette_colors = sns.color_palette("tab10", n_colors=len(all_decls))
color_map = dict(zip(all_decls, palette_colors))

# 3. Setup the Figure
sns.set_style("white")  # Using "white" style to ensure borders aren't hidden
fig, axes = plt.subplots(2, 4, figsize=(18, 10), sharex=False, sharey='row')

# --- PLOT TOP ROW ---
for i, decl in enumerate(top_row_decls):
    ax = axes[0, i]
    subset = df[df['DECLARATIE'] == decl]

    sns.barplot(data=subset, x='AN', y='VALOARE', color=color_map[decl], ax=ax)

    ax.set_title(decl, fontsize=14, fontweight='bold', color=color_map[decl])
    ax.set_xlabel('')
    ax.set_ylabel('')

    # Formatter
    if i == 0:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, pos: '%1.0fM' % (x * 1e-6)))

    # --- SEPARATION LINES (CRITICAL PART) ---
    # Hide Left Spine (except for the very first chart)
    if i > 0:
        ax.spines['left'].set_visible(False)
        ax.tick_params(axis='y', left=False)  # Hide ticks

    # Force Right Spine to be VISIBLE and BLACK
    # We do this for all except the very last one (optional, but looks cleaner closed)
    ax.spines['right'].set_visible(True)
    ax.spines['right'].set_color('black')
    ax.spines['right'].set_linewidth(1.5)  # Thicker line to be seen

# --- PLOT BOTTOM ROW ---
for i, decl in enumerate(bottom_row_decls):
    ax = axes[1, i]
    subset = df[df['DECLARATIE'] == decl]

    sns.barplot(data=subset, x='AN', y='VALOARE', color=color_map[decl], ax=ax)

    ax.set_title(decl, fontsize=14, fontweight='bold', color=color_map[decl])
    ax.set_xlabel('')
    ax.set_ylabel('')

    # Formatter
    if i == 0:
        def custom_fmt(x, pos):
            if x >= 1_000_000:
                return '%1.1fM' % (x * 1e-6)
            elif x >= 1000:
                return '%1.0fK' % (x * 1e-3)
            else:
                return '%1.0f' % x


        ax.yaxis.set_major_formatter(FuncFormatter(custom_fmt))

    # --- SEPARATION LINES ---
    if i > 0:
        ax.spines['left'].set_visible(False)
        ax.tick_params(axis='y', left=False)

    # Force Right Spine
    ax.spines['right'].set_visible(True)
    ax.spines['right'].set_color('black')
    ax.spines['right'].set_linewidth(1.5)

# Turn off the empty chart
axes[1, 3].axis('off')

# 4. Legend
legend_elements = [Patch(facecolor=color_map[decl], label=decl) for decl in all_decls]
fig.legend(handles=legend_elements, loc='upper center', bbox_to_anchor=(0.5, 0.95),
           ncol=len(all_decls), fontsize=12, frameon=False, title="Declaration Type")

# 5. Final Adjustments
fig.suptitle('Value by Declaration', fontsize=20, y=0.98)
fig.text(0.005, 0.75, 'Millions (M)', va='center', rotation='vertical', fontsize=12, fontweight='bold')
fig.text(0.005, 0.25, 'Thousands (K)', va='center', rotation='vertical', fontsize=12, fontweight='bold')

# SQUEEZE TOGETHER
plt.tight_layout(rect=[0.02, 0, 1, 0.90])
plt.subplots_adjust(wspace=0, hspace=0.3)

plt.show()