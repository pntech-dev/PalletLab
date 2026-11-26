import { Info } from "lucide-react";
import lengthIcon from "../assets/summary/length.svg";
import widthIcon from "../assets/summary/width.svg";
import heightIcon from "../assets/summary/height.svg";
import weightIcon from "../assets/summary/weight.svg";
import beamPreview from "../assets/summary/beam.svg";

type Detail = { height: number; width: number; length: number; count: number };
type Props = {
  size: { length: number; width: number; height: number };
  mass: number;
  details: Detail[];
  millimetres: (value: number) => string;
  kilograms: (value: number) => string;
};

export function detailCount(count: number) {
  const lastTwo = count % 100;
  const ending = lastTwo >= 11 && lastTwo <= 14 ? "деталей" : count % 10 === 1 ? "деталь" :
    count % 10 >= 2 && count % 10 <= 4 ? "детали" : "деталей";
  return `${count} ${ending}`;
}

export function PalletSummary({ size, mass, details, millimetres, kilograms }: Props) {
  const metrics = [
    { label: "Длина", value: `${millimetres(size.length)} мм`, icon: lengthIcon, color: "length" },
    { label: "Ширина", value: `${millimetres(size.width)} мм`, icon: widthIcon, color: "width" },
    { label: "Высота", value: `${millimetres(size.height)} мм`, icon: heightIcon, color: "height" },
    { label: "Масса", value: `${kilograms(mass)} кг`, icon: weightIcon, color: "weight" },
  ];
  const total = details.reduce((sum, detail) => sum + detail.count, 0);
  return <div className="pallet-summary">
    <section className="pallet-summary-card pallet-sizes-card" aria-label="Габариты поддона">
      <h2>Габариты поддона</h2>
      <dl className="pallet-summary-sizes">{metrics.map((metric) => <div className="pallet-metric" key={metric.label}>
        <span className={`pallet-metric-icon is-${metric.color}`} aria-hidden="true"><img src={metric.icon} alt="" /></span>
        <div><dt>{metric.label}</dt><dd>{metric.value}</dd></div>
      </div>)}</dl>
      <p className="pallet-summary-note"><Info size={16} aria-hidden="true" /> Габариты поддона указаны без учёта размещённых на нём моделей</p>
    </section>
    <section className="pallet-summary-card pallet-details-card" aria-label="Детали поддона">
      <header><h2>Детали</h2><span>{detailCount(total)}</span></header>
      <div className="pallet-details-scroll" tabIndex={0} aria-label="Список деталей поддона">
        {details.map((detail) => <div className="pallet-detail" key={`${detail.height}-${detail.width}-${detail.length}`}>
          <img src={beamPreview} alt="" />
          <div><strong>Брус {millimetres(detail.height)} × {millimetres(detail.width)} × {millimetres(detail.length)} мм</strong><span>Кол-во: {detail.count} шт.</span></div>
        </div>)}
      </div>
    </section>
  </div>;
}
