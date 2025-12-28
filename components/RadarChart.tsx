import React from 'react';
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip
} from 'recharts';
import { CategoryResult } from '../types';

interface RadarChartProps {
  data: CategoryResult[];
}

const Chart: React.FC<RadarChartProps> = ({ data }) => {
  // Format data for Recharts
  const chartData = data.map(item => ({
    subject: item.title.replace(/^[一二三四五]、/, ''),
    A: item.percentage,
    fullMark: 100
  }));

  return (
    <div className="w-full h-80">
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart cx="50%" cy="50%" outerRadius="80%" data={chartData}>
          <PolarGrid />
          <PolarAngleAxis dataKey="subject" tick={{ fill: '#4b5563', fontSize: 12 }} />
          <PolarRadiusAxis angle={30} domain={[0, 100]} />
          <Radar
            name="得分率 (%)"
            dataKey="A"
            stroke="#16a34a"
            fill="#4ade80"
            fillOpacity={0.6}
          />
          <Tooltip formatter={(value: number) => [`${value.toFixed(1)}%`, '得分率']} />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default Chart;