import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
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

# 2. Define the Groups
top_row_decls = ['D112', 'D205', 'D224', 'DUF']
bottom_row_decls = ['D208', 'RIF', 'D209']

# 3. Setup the Figure
# CHANGE: sharey='row' makes Row 1 share a scale, and Row 2 share a different scale
fig, axes = plt.subplots(2, 4, figsize=(18, 10), sharex=False, sharey='row')

# --- PLOT TOP ROW ---
for i, decl in enumerate(top_row_decls):
    ax = axes[0, i]
    subset = df[df['DECLARATIE'] == decl]

    sns.barplot(data=subset, x='AN', y='VALOARE', hue='AN', ax=ax, palette='viridis', legend=False)

    ax.set_title(decl, fontsize=14, fontweight='bold')
    ax.set_xlabel('')
    ax.set_ylabel('')

    # Format Top Row as Millions
    # Note: With sharey='row', this format applies to the whole top row automatically
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, pos: '%1.0fM' % (x * 1e-6)))

# --- PLOT BOTTOM ROW ---
for i, decl in enumerate(bottom_row_decls):
    ax = axes[1, i]
    subset = df[df['DECLARATIE'] == decl]

    sns.barplot(data=subset, x='AN', y='VALOARE', hue='AN', ax=ax, palette='plasma', legend=False)

    ax.set_title(decl, fontsize=14, fontweight='bold')
    ax.set_xlabel('')
    ax.set_ylabel('')


    # Format Bottom Row (Custom: K or M)
    # This row has smaller values (max ~2M), so we use a flexible formatter
    def custom_fmt(x, pos):
        if x >= 1_000_000:
            return '%1.1fM' % (x * 1e-6)
        elif x >= 1000:
            return '%1.0fK' % (x * 1e-3)
        else:
            return '%1.0f' % x


    ax.yaxis.set_major_formatter(FuncFormatter(custom_fmt))

# Turn off empty chart
axes[1, 3].axis('off')

# 5. Final Adjustments
fig.suptitle('Value by Declaration (Shared by Row)', fontsize=20)

# Add text labels manually since sharey hides the inner y-labels
fig.text(0.005, 0.75, 'Row 1 Scale (Millions)', va='center', rotation='vertical', fontsize=12, fontweight='bold')
fig.text(0.005, 0.25, 'Row 2 Scale (Thousands/Low Millions)', va='center', rotation='vertical', fontsize=12,
         fontweight='bold')

plt.tight_layout(rect=[0.02, 0, 1, 0.95])
plt.show()