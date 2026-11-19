import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "src/Plans.tsx", '<div className="plan-list">', '<div className="plan-list" data-testid="plan-row">')
replace(repo, "src/Plans.tsx", '<section className="plan">', '<section className="plan" data-testid="plan-card">')
append(repo, "src/styles.css", '''
.plans {
  max-width: 1100px;
}

.plan-list {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 24px;
}

.plan {
  width: 320px;
}

@media (max-width: 720px) {
  .plan-list {
    flex-direction: column;
  }

  .plan {
    width: 100%;
  }
}
''')
