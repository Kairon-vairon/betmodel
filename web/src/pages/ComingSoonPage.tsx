const PAGES: Record<string, { title: string; text: string; when: string }> = {
  '/value-bets': {
    title: 'Value bets',
    text: 'Bookmaker prices that beat the Betfair fair price by 3% or more, with the stake, the lowest odds worth taking and Placed / Skip buttons.',
    when: 'Shows bets once data ingestion (Milestone 2) feeds the value finder.',
  },
  '/bet-log': {
    title: 'Bet log',
    text: 'Every suggested bet: placed, skipped or expired, graded automatically from final scores, with closing line value.',
    when: 'Arrives with Milestone 5. The grading rules are already built and tested.',
  },
  '/performance': {
    title: 'Model & performance',
    text: 'Profit, closing line value and calibration over time, by league, and shadow models compared with the live one.',
    when: 'After Phase 1, once there are settled bets to measure.',
  },
  '/analyst': {
    title: 'Claude analyst',
    text: 'Plain-English explanations of each bet, a weekly review, and answers to your questions about your own data.',
    when: 'After Phase 1.',
  },
  '/lab': {
    title: 'Lab & releases',
    text: "Claude's version, its experiments and release proposals, with Upgrade, Reject and one-tap rollback.",
    when: 'After Phase 1.',
  },
}

export function ComingSoonPage({ path }: { path: string }) {
  const page = PAGES[path]
  if (!page) {
    return (
      <div className="page-head">
        <div>
          <h1>Page not found</h1>
          <p className="lede">There's nothing at this address.</p>
        </div>
      </div>
    )
  }
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Coming soon</div>
          <h1>{page.title}</h1>
          <p className="lede">{page.text}</p>
        </div>
      </div>
      <section className="card">
        <span className="label">When</span>
        <span>{page.when}</span>
      </section>
    </>
  )
}
