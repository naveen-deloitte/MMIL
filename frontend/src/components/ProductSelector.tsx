import { useEffect, useId, useMemo, useRef, useState } from "react";

import { ApiError, loadProduct, loadProducts, quoteProduct } from "../api";
import type {
  AmountRange,
  IndicativeQuote,
  PremiumFrequency,
  ProductDetail,
  ProductList,
  ProductListItem,
  ProductSelection,
  RatingInputs,
  TermRange,
} from "../types";

const NOT_AVAILABLE = "Not Available";

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.problem.detail;
  return error instanceof Error ? error.message : "The operation could not be completed.";
}

function money(amount: number | null | undefined, currency: string | null | undefined): string {
  if (amount === null || amount === undefined) return NOT_AVAILABLE;
  if (!currency) return amount.toLocaleString("en-IN");
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 2 }).format(amount);
  } catch {
    return `${currency} ${amount.toLocaleString("en-IN")}`;
  }
}

function years(value: number | "policy_term"): string {
  return value === "policy_term" ? "Same as policy term" : `${value} years`;
}

/** Exactly one permitted value, so it is shown as fixed rather than as a choice. */
function only<T>(values: T[] | undefined): T | undefined {
  return values && values.length === 1 ? values[0] : undefined;
}

function resolveTerm(value: number | "policy_term" | undefined, policyTerm: number | undefined) {
  return value === "policy_term" ? policyTerm : value;
}

interface ProductSelectorProps {
  onChange: (selection: ProductSelection | null, product: ProductDetail | null) => void;
  /** Called once the catalogue loads so the form knows whether products are configured. */
  onCatalogueLoaded?: (list: ProductList) => void;
}

export function ProductSelector({ onChange, onCatalogueLoaded }: ProductSelectorProps) {
  const [catalogue, setCatalogue] = useState<ProductList | null>(null);
  const [catalogueError, setCatalogueError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [selected, setSelected] = useState<ProductListItem | null>(null);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const loadedCallback = useRef(onCatalogueLoaded);
  loadedCallback.current = onCatalogueLoaded;

  async function fetchCatalogue() {
    setCatalogueError(null);
    try {
      const list = await loadProducts();
      setCatalogue(list);
      loadedCallback.current?.(list);
    } catch (error) {
      setCatalogueError(messageFor(error));
    }
  }

  useEffect(() => {
    void fetchCatalogue();
  }, []);

  const matches = useMemo(() => {
    const tokens = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
    return (catalogue?.items ?? []).filter((item) => {
      const haystack = [item.product_name, item.insurer, item.insurance_type ?? ""].join(" ").toLocaleLowerCase();
      return tokens.every((token) => haystack.includes(token));
    });
  }, [catalogue, query]);

  async function choose(item: ProductListItem) {
    setSelected(item);
    setQuery(item.product_name);
    setOpen(false);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    onChange(null, null);
    try {
      setDetail(await loadProduct(item.product_id));
    } catch (error) {
      setDetailError(messageFor(error));
    } finally {
      setDetailLoading(false);
    }
  }

  function clearSelection() {
    setSelected(null);
    setDetail(null);
    setDetailError(null);
    setQuery("");
    onChange(null, null);
    setOpen(true);
    inputRef.current?.focus();
  }

  if (catalogueError) {
    return (
      <div className="product-selector">
        <div className="form-error" role="alert">
          Product catalogue unavailable: {catalogueError}{" "}
          <button type="button" className="text-button" onClick={() => void fetchCatalogue()}>Try again</button>
        </div>
      </div>
    );
  }
  if (!catalogue) return <p className="data-note" role="status">Loading product catalogue…</p>;
  if (!catalogue.catalogue_configured || catalogue.items.length === 0) return null;

  return (
    <div className="product-selector">
      <label className="form-field product-search-field" htmlFor={`${listId}-input`}>
        Insurance product
        <span className="product-combobox">
          <input
            id={`${listId}-input`}
            ref={inputRef}
            role="combobox"
            aria-expanded={open}
            aria-controls={`${listId}-list`}
            aria-autocomplete="list"
            aria-activedescendant={open && matches[highlight] ? `${listId}-${matches[highlight].product_id}` : undefined}
            autoComplete="off"
            placeholder="Search by product, insurer or type"
            value={query}
            onFocus={() => setOpen(true)}
            onBlur={() => window.setTimeout(() => setOpen(false), 150)}
            onChange={(event) => {
              setQuery(event.target.value);
              setOpen(true);
              setHighlight(0);
              if (selected && event.target.value !== selected.product_name) {
                setSelected(null);
                setDetail(null);
                onChange(null, null);
              }
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setOpen(true);
                setHighlight((current) => Math.min(current + 1, Math.max(matches.length - 1, 0)));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setHighlight((current) => Math.max(current - 1, 0));
              } else if (event.key === "Enter" && open && matches[highlight]) {
                event.preventDefault();
                void choose(matches[highlight]);
              } else if (event.key === "Escape") {
                setOpen(false);
              }
            }}
          />
          {selected ? (
            <button type="button" className="text-button product-change" onClick={clearSelection}>
              Change product
            </button>
          ) : null}
        </span>
      </label>
      {open ? (
        <ul className="product-options" id={`${listId}-list`} role="listbox" aria-label="Insurance products">
          {matches.length === 0 ? (
            <li className="product-option-empty">No products match “{query}”.</li>
          ) : (
            matches.map((item, index) => (
              <li
                key={item.product_id}
                id={`${listId}-${item.product_id}`}
                role="option"
                aria-selected={selected?.product_id === item.product_id}
                className={index === highlight ? "highlighted" : ""}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setHighlight(index)}
                onClick={() => void choose(item)}
              >
                <strong>{item.product_name}</strong>
                <small>{item.insurer}{item.insurance_type ? ` · ${item.insurance_type}` : ""}</small>
              </li>
            ))
          )}
        </ul>
      ) : null}
      {catalogue.demo_catalogue ? (
        <p className="product-demo-note">
          Demo product catalogue. Products, insurers and rates are fictional. Replace it with the
          insurer's approved catalogue before real use.
        </p>
      ) : null}
      {detailLoading ? <p className="data-note" role="status">Loading product details…</p> : null}
      {detailError ? <div className="form-error" role="alert">{detailError}</div> : null}
      {detail ? <ProductDetailsCard key={detail.product_id} product={detail} onChange={onChange} /> : null}
    </div>
  );
}

function ProductDetailsCard({
  product,
  onChange,
}: {
  product: ProductDetail;
  onChange: ProductSelectorProps["onChange"];
}) {
  const sumAssuredRange: AmountRange | null = product.sum_assured;
  const currency = sumAssuredRange?.currency ?? null;
  const [sumAssured, setSumAssured] = useState<number | undefined>(only(sumAssuredRange?.options));
  const [frequency, setFrequency] = useState<PremiumFrequency | undefined>(only(product.premium_frequencies ?? undefined)?.value);
  const [policyTerm, setPolicyTerm] = useState<number | undefined>(() => {
    const value = only(product.policy_terms?.options);
    return typeof value === "number" ? value : undefined;
  });
  const [paymentTermChoice, setPaymentTermChoice] = useState<number | "policy_term" | undefined>(
    only(product.premium_payment_terms?.options),
  );
  const [rating, setRating] = useState<RatingInputs>({});
  const [quote, setQuote] = useState<IndicativeQuote | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [quoting, setQuoting] = useState(false);

  const paymentTerm = resolveTerm(paymentTermChoice, policyTerm);
  const needs = new Set(product.rating_factors);

  useEffect(() => {
    const selection: ProductSelection = {
      product_id: product.product_id,
      ...(sumAssured !== undefined ? { sum_assured: sumAssured } : {}),
      ...(frequency ? { premium_frequency: frequency } : {}),
      ...(policyTerm !== undefined ? { policy_term: policyTerm } : {}),
      ...(paymentTerm !== undefined ? { premium_payment_term: paymentTerm } : {}),
      rating,
    };
    onChange(selection, product);
    if (!product.pricing_available) {
      setQuote(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setQuoting(true);
      setQuoteError(null);
      const { product_id: _id, ...request } = selection;
      quoteProduct(product.product_id, request)
        .then((result) => { if (!cancelled) setQuote(result); })
        .catch((error) => { if (!cancelled) setQuoteError(messageFor(error)); })
        .finally(() => { if (!cancelled) setQuoting(false); });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // onChange is a stable parent setter; listing it would refetch on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product, sumAssured, frequency, policyTerm, paymentTerm, rating]);

  return (
    <section className="product-details-card" aria-label="Product details">
      <div className="product-details-heading">
        <h3>Product details</h3>
        <span className="muted">From catalogue {product.catalogue.catalogue_id} v{product.catalogue.catalogue_version}</span>
      </div>
      {product.description ? <p className="product-description">{product.description}</p> : null}
      <dl className="product-details-grid">
        <DetailRow label="Insurance company" value={product.insurer} />
        <DetailRow label="Insurance type" value={product.insurance_type} />
        <DetailRow label="Insurance plan / product name" value={product.plan_name ?? product.product_name} />
        {product.uin ? <DetailRow label="Product UIN" value={product.uin} /> : null}
        <div className="product-detail-row">
          <dt>Sum assured / coverage</dt>
          <dd>
            <AmountChooser range={sumAssuredRange} value={sumAssured} onChange={setSumAssured} />
          </dd>
        </div>
        <div className="product-detail-row">
          <dt>Premium frequency</dt>
          <dd>
            {!product.premium_frequencies ? (
              NOT_AVAILABLE
            ) : product.premium_frequencies.length === 1 ? (
              product.premium_frequencies[0].label
            ) : (
              <select
                aria-label="Premium frequency"
                value={frequency ?? ""}
                onChange={(event) => setFrequency((event.target.value || undefined) as PremiumFrequency | undefined)}
              >
                <option value="">Select frequency</option>
                {product.premium_frequencies.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            )}
          </dd>
        </div>
        <div className="product-detail-row">
          <dt>Policy term</dt>
          <dd>
            <TermChooser
              label="Policy term"
              range={product.policy_terms}
              value={policyTerm}
              onChange={(value) => setPolicyTerm(typeof value === "number" ? value : undefined)}
            />
          </dd>
        </div>
        <div className="product-detail-row">
          <dt>Premium payment term</dt>
          <dd>
            <TermChooser
              label="Premium payment term"
              range={product.premium_payment_terms}
              value={paymentTermChoice}
              policyTerm={policyTerm}
              onChange={setPaymentTermChoice}
            />
          </dd>
        </div>
        {product.entry_age_min !== null || product.entry_age_max !== null ? (
          <DetailRow
            label="Entry age"
            value={`${product.entry_age_min ?? "?"}–${product.entry_age_max ?? "?"} years`}
          />
        ) : null}
      </dl>

      <div className="product-premium">
        <div className="product-premium-heading">
          <h4>Premium amount</h4>
          <span className="identity-badge premium-indicative-badge">Indicative · not an official insurer quote</span>
        </div>
        {!product.pricing_available ? (
          <p><strong>{NOT_AVAILABLE}</strong> <span className="muted">No pricing rules are configured for this product. An insurer quote is required.</span></p>
        ) : (
          <>
            {needs.size ? (
              <div className="product-rating-inputs">
                <span className="muted">The premium depends on these applicant details:</span>
                {needs.has("age") ? (
                  <label>
                    Age
                    <input
                      type="number"
                      min={0}
                      max={120}
                      aria-label="Applicant age"
                      value={rating.age ?? ""}
                      onChange={(event) => setRating((current) => ({
                        ...current,
                        age: event.target.value === "" ? undefined : Number(event.target.value),
                      }))}
                    />
                  </label>
                ) : null}
                {needs.has("gender") ? (
                  <label>
                    Gender
                    <select
                      aria-label="Applicant gender"
                      value={rating.gender ?? ""}
                      onChange={(event) => setRating((current) => ({
                        ...current,
                        gender: (event.target.value || undefined) as RatingInputs["gender"],
                      }))}
                    >
                      <option value="">Select</option>
                      <option value="male">Male</option>
                      <option value="female">Female</option>
                      <option value="other">Other</option>
                    </select>
                  </label>
                ) : null}
                {needs.has("smoker") ? (
                  <label>
                    Tobacco / smoker
                    <select
                      aria-label="Smoking status"
                      value={rating.smoker === undefined ? "" : String(rating.smoker)}
                      onChange={(event) => setRating((current) => ({
                        ...current,
                        smoker: event.target.value === "" ? undefined : event.target.value === "true",
                      }))}
                    >
                      <option value="">Select</option>
                      <option value="false">Non-smoker</option>
                      <option value="true">Smoker</option>
                    </select>
                  </label>
                ) : null}
              </div>
            ) : null}
            <QuoteResultView quote={quote} quoting={quoting} error={quoteError} />
          </>
        )}
      </div>
    </section>
  );
}

function DetailRow({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="product-detail-row">
      <dt>{label}</dt>
      <dd className={value ? "" : "not-available"}>{value || NOT_AVAILABLE}</dd>
    </div>
  );
}

function AmountChooser({
  range,
  value,
  onChange,
}: {
  range: AmountRange | null;
  value: number | undefined;
  onChange: (value: number | undefined) => void;
}) {
  if (!range) return <span className="not-available">{NOT_AVAILABLE}</span>;
  if (range.options && range.options.length === 1) return <>{money(range.options[0], range.currency)}</>;
  if (range.options) {
    return (
      <select
        aria-label="Sum assured"
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value === "" ? undefined : Number(event.target.value))}
      >
        <option value="">Select sum assured</option>
        {range.options.map((option) => (
          <option key={option} value={option}>{money(option, range.currency)}</option>
        ))}
      </select>
    );
  }
  return (
    <span className="product-range-input">
      <input
        type="number"
        aria-label="Sum assured"
        min={range.min}
        max={range.max}
        step={range.step}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value === "" ? undefined : Number(event.target.value))}
      />
      <small className="muted">
        {money(range.min, range.currency)} to {money(range.max, range.currency)}
        {range.step ? `, in steps of ${money(range.step, range.currency)}` : ""}
      </small>
    </span>
  );
}

function TermChooser({
  label,
  range,
  value,
  policyTerm,
  onChange,
}: {
  label: string;
  range: TermRange | null;
  value: number | "policy_term" | undefined;
  policyTerm?: number;
  onChange: (value: number | "policy_term" | undefined) => void;
}) {
  if (!range) return <span className="not-available">{NOT_AVAILABLE}</span>;
  if (range.options && range.options.length === 1) {
    const option = range.options[0];
    if (option === "policy_term") {
      return <>{policyTerm ? `${policyTerm} years (same as policy term)` : "Same as policy term"}</>;
    }
    return <>{years(option)}</>;
  }
  if (range.options) {
    return (
      <select
        aria-label={label}
        value={value === undefined ? "" : String(value)}
        onChange={(event) => {
          const raw = event.target.value;
          onChange(raw === "" ? undefined : raw === "policy_term" ? "policy_term" : Number(raw));
        }}
      >
        <option value="">Select term</option>
        {range.options.map((option) => (
          <option key={String(option)} value={String(option)}>{years(option)}</option>
        ))}
      </select>
    );
  }
  return (
    <span className="product-range-input">
      <input
        type="number"
        aria-label={label}
        min={range.min}
        max={range.max}
        value={typeof value === "number" ? value : ""}
        onChange={(event) => onChange(event.target.value === "" ? undefined : Number(event.target.value))}
      />
      <small className="muted">{range.min} to {range.max} years</small>
    </span>
  );
}

const PER_FREQUENCY: Record<string, string> = {
  single: "single premium",
  annual: "per year",
  half_yearly: "per half-year",
  quarterly: "per quarter",
  monthly: "per month",
};

const INPUT_LABELS: Record<string, string> = {
  sum_assured: "sum assured",
  premium_frequency: "premium frequency",
  policy_term: "policy term",
  age: "age",
  gender: "gender",
  smoker: "smoking status",
};

function QuoteResultView({
  quote,
  quoting,
  error,
}: {
  quote: IndicativeQuote | null;
  quoting: boolean;
  error: string | null;
}) {
  if (error) return <div className="form-error" role="alert">{error}</div>;
  if (!quote) return <p className="muted" role="status">{quoting ? "Calculating…" : ""}</p>;
  if (quote.status !== "indicative") {
    return (
      <div className="product-quote not-available" aria-live="polite">
        <strong>{NOT_AVAILABLE}</strong>
        {quote.missing_inputs.length ? (
          <span> · Enter {quote.missing_inputs.map((name) => INPUT_LABELS[name] ?? name).join(", ")}.</span>
        ) : null}
        {quote.reasons.filter((reason) => !quote.missing_inputs.length || !reason.startsWith("Enter")).map((reason) => (
          <span key={reason}> {reason}</span>
        ))}
      </div>
    );
  }
  return (
    <div className="product-quote" aria-live="polite">
      <strong className="product-quote-amount">{money(quote.amount, quote.currency)}</strong>
      {quote.premium_frequency ? <span className="muted"> {PER_FREQUENCY[quote.premium_frequency] ?? ""}</span> : null}
      {quote.tax_amount !== null ? (
        <small className="muted">
          Includes tax of {money(quote.tax_amount, quote.currency)} on {money(quote.amount_before_tax, quote.currency)}
        </small>
      ) : null}
      {quote.basis_note ? <small className="muted">Basis: {quote.basis_note}</small> : null}
      <small className="product-quote-disclaimer">{quote.disclaimer}</small>
    </div>
  );
}
