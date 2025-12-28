import React, { useState, useEffect, useMemo } from 'react';
import { BasicInfo, Question, CategoryResult, Tabs } from './types';
import { QUESTIONS } from './questions';
import { TAIWAN_CITIES, INDUSTRIES, INTRO_TEXT, EVALUATION_TEXT, SUGGESTIONS_DATA } from './constants';
import Chart from './components/RadarChart';
import { 
  FileText, ClipboardList, CheckSquare, Activity, AlertCircle, 
  ChevronRight, ChevronLeft, Briefcase, Search, Heart, Wind, 
  Users, Zap, Utensils, Scale, Ban, ShieldCheck, Smile, Check, X,
  Info
} from 'lucide-react';

// Icon Mapping
const ICON_MAP: Record<string, any> = {
  Briefcase, Search, Activity, Utensils, Scale, Ban, ShieldCheck, Smile, Wind, Users
};

// Custom Dialog Component for Alerts
const AlertDialog = ({ isOpen, title, message, onClose }: { isOpen: boolean; title: string; message: string; onClose: () => void }) => {
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 px-4 backdrop-blur-sm transition-opacity duration-300">
      <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-6 animate-slide-up transform transition-all">
        <div className="flex items-center mb-4 text-red-600">
          <AlertCircle className="w-7 h-7 mr-3" />
          <h3 className="text-xl font-bold">{title}</h3>
        </div>
        <p className="text-gray-700 mb-8 text-lg leading-relaxed">{message}</p>
        <div className="flex justify-end">
          <button
            onClick={onClose}
            className="px-6 py-2 bg-primary-600 text-white rounded-lg font-medium hover:bg-primary-700 hover:shadow-lg transition-all active:scale-95"
          >
            確定
          </button>
        </div>
      </div>
    </div>
  );
};

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<Tabs>(Tabs.INTRO);
  const [basicInfo, setBasicInfo] = useState<BasicInfo>({
    unitName: '',
    taxId: '',
    city: '',
    district: '',
    unitType: '',
    unitTypeOther: '',
    schoolType: '',
    hospitalType: '',
    industry: '',
    employeesMale: 0,
    employeesFemale: 0,
    scale: '',
    contactName: '',
    contactDept: '',
    contactTitle: '',
    contactPhone: '',
    contactEmail: ''
  });
  
  // Record<QuestionID, Score>
  const [answers, setAnswers] = useState<Record<number, boolean | null>>({});
  
  // Alert State
  const [alertState, setAlertState] = useState({ isOpen: false, title: '', message: '' });

  // Scroll to top on tab change
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [activeTab]);

  // Handle Basic Info Change & Scale Calculation
  const handleBasicInfoChange = (field: keyof BasicInfo, value: any) => {
    // We use functional state update here to avoid race conditions if multiple fields update quickly
    setBasicInfo(prev => {
      const newInfo = { ...prev, [field]: value };
      
      // Auto-calculate scale if employees change
      if (field === 'employeesMale' || field === 'employeesFemale') {
        const male = field === 'employeesMale' ? Number(value) : Number(prev.employeesMale);
        const female = field === 'employeesFemale' ? Number(value) : Number(prev.employeesFemale);
        const total = male + female;
        
        let scale = '';
        if (total >= 300) scale = '大型職場';
        else if (total >= 100) scale = '中型職場';
        else scale = '小型職場';
        newInfo.scale = scale;
      }
      return newInfo;
    });
  };

  // Specific handler for City to ensure District is reset properly without race conditions
  const handleCityChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setBasicInfo(prev => ({
      ...prev,
      city: e.target.value,
      district: ''
    }));
  };

  const handleAnswerChange = (questionId: number, value: boolean) => {
    setAnswers(prev => ({
      ...prev,
      [questionId]: value
    }));
  };

  const validateAndSubmit = () => {
    // 1. Check Basic Info (Simple check)
    if (!basicInfo.unitName) {
      setAlertState({ isOpen: true, title: '資料未完成', message: '請填寫單位名稱。' });
      setActiveTab(Tabs.BASIC_INFO);
      return;
    }

    // 2. Check Questions
    for (const q of QUESTIONS) {
      if (answers[q.id] === undefined || answers[q.id] === null) {
        const partNames = ["", "一", "二", "三", "四", "五"];
        setAlertState({
          isOpen: true, 
          title: '問卷未完成', 
          message: `第${partNames[q.partId]}大題的第${q.id}題未完成` 
        });
        setActiveTab(Tabs.QUESTIONNAIRE);
        
        // Scroll to question
        setTimeout(() => {
            const el = document.getElementById(`q-${q.id}`);
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 300);
        return;
      }
    }

    // All good, go to result
    setActiveTab(Tabs.RESULT);
  };

  const calculateResults = (): { categoryResults: CategoryResult[], totalScore: number } => {
    const categoryResults: CategoryResult[] = [];
    let totalScore = 0;

    // Group questions by part
    const parts = [1, 2, 3, 4, 5];
    const partTitles = [
      "",
      "一、職場健康政策與計畫",
      "二、職場健康需求評估",
      "三、健康促進設施與活動",
      "四、生理健康工作環境",
      "五、社區參與"
    ];

    parts.forEach(partId => {
      const partQuestions = QUESTIONS.filter(q => q.partId === partId);
      const totalPoints = partQuestions.reduce((sum, q) => sum + q.points, 0);
      const earnedPoints = partQuestions.reduce((sum, q) => {
        return sum + (answers[q.id] ? q.points : 0);
      }, 0);

      categoryResults.push({
        partId,
        title: partTitles[partId],
        score: earnedPoints,
        totalPoints,
        percentage: totalPoints === 0 ? 0 : (earnedPoints / totalPoints) * 100
      });
      totalScore += earnedPoints;
    });

    return { categoryResults, totalScore };
  };

  const getEvaluation = (score: number) => {
    return EVALUATION_TEXT.find(e => score >= e.range[0] && score <= e.range[1]) || EVALUATION_TEXT[0];
  };

  const renderIntro = () => (
    <div className="bg-white p-8 md:p-12 rounded-2xl shadow-lg border border-gray-100 animate-slide-up max-w-4xl mx-auto">
      <div className="flex flex-col items-center mb-8">
        <div className="p-4 bg-primary-100 rounded-full mb-4 shadow-inner">
          <Activity className="w-12 h-12 text-primary-600" />
        </div>
        <h2 className="text-3xl font-bold text-gray-900">說明</h2>
      </div>
      
      <div className="prose prose-lg max-w-none text-gray-700 whitespace-pre-line leading-relaxed">
        {INTRO_TEXT}
      </div>
      <div className="mt-10 flex justify-center">
        <button 
          onClick={() => setActiveTab(Tabs.BASIC_INFO)}
          className="flex items-center gap-3 px-8 py-4 bg-gradient-to-r from-primary-600 to-primary-700 text-white rounded-xl shadow-lg hover:shadow-xl hover:scale-105 transition-all font-bold text-lg group"
        >
          開始填寫 <ChevronRight className="group-hover:translate-x-1 transition-transform" />
        </button>
      </div>
    </div>
  );

  const renderBasicInfo = () => (
    <div className="max-w-4xl mx-auto bg-white p-8 md:p-10 rounded-2xl shadow-lg border border-gray-100 animate-slide-up">
      <div className="flex items-center gap-3 mb-8 border-b pb-4">
        <div className="p-2 bg-blue-100 rounded-lg text-blue-600">
           <ClipboardList size={28} />
        </div>
        <h2 className="text-2xl font-bold text-gray-800">基本資料</h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        
        <div className="col-span-2 md:col-span-1 space-y-1">
          <label className="block text-sm font-semibold text-gray-700">1. 單位名稱</label>
          <input 
            type="text" 
            className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none transition-shadow hover:shadow-sm"
            value={basicInfo.unitName}
            placeholder="請輸入公司/單位全名"
            onChange={(e) => handleBasicInfoChange('unitName', e.target.value)}
          />
        </div>

        <div className="col-span-2 md:col-span-1 space-y-1">
          <label className="block text-sm font-semibold text-gray-700">2. 統一編號</label>
          <input 
            type="text" 
            className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none transition-shadow hover:shadow-sm"
            value={basicInfo.taxId}
            placeholder="8碼統編"
            onChange={(e) => handleBasicInfoChange('taxId', e.target.value)}
          />
        </div>

        <div className="col-span-2 space-y-1">
          <label className="block text-sm font-semibold text-gray-700">3. 單位地址</label>
          <div className="flex gap-4">
            <select 
              className="w-1/3 p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none hover:bg-gray-50"
              value={basicInfo.city}
              onChange={handleCityChange}
            >
              <option value="">請選擇縣市</option>
              {Object.keys(TAIWAN_CITIES).map(city => (
                <option key={city} value={city}>{city}</option>
              ))}
            </select>
            <select 
              className="w-1/3 p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none hover:bg-gray-50 disabled:bg-gray-100"
              value={basicInfo.district}
              onChange={(e) => handleBasicInfoChange('district', e.target.value)}
              disabled={!basicInfo.city}
            >
              <option value="">請選擇區鄉鎮</option>
              {basicInfo.city && TAIWAN_CITIES[basicInfo.city]?.map(dist => (
                <option key={dist} value={dist}>{dist}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="col-span-2 space-y-2">
          <label className="block text-sm font-semibold text-gray-700">4. 單位類別</label>
          <div className="grid grid-cols-2 gap-3 p-4 bg-gray-50 rounded-xl border border-gray-100">
            {['民間企業', '公營企業', '政府機關'].map(type => (
              <label key={type} className="flex items-center gap-3 p-2 rounded hover:bg-white transition-colors cursor-pointer">
                <input 
                  type="radio" 
                  name="unitType"
                  value={type}
                  checked={basicInfo.unitType === type}
                  onChange={(e) => handleBasicInfoChange('unitType', e.target.value)}
                  className="w-4 h-4 text-primary-600 focus:ring-primary-500"
                />
                <span className="text-gray-700">{type}</span>
              </label>
            ))}
            
            <label className="flex items-center gap-3 p-2 rounded hover:bg-white transition-colors cursor-pointer">
               <input 
                  type="radio" 
                  name="unitType"
                  value="學校機關"
                  checked={basicInfo.unitType === '學校機關'}
                  onChange={(e) => handleBasicInfoChange('unitType', e.target.value)}
                  className="w-4 h-4 text-primary-600 focus:ring-primary-500"
                />
               <span className="text-gray-700">學校機關</span>
               {basicInfo.unitType === '學校機關' && (
                 <select 
                   className="ml-2 p-1 text-sm border border-gray-300 rounded focus:ring-1 focus:ring-primary-500"
                   value={basicInfo.schoolType}
                   onChange={(e) => handleBasicInfoChange('schoolType', e.target.value)}
                   onClick={(e) => e.stopPropagation()}
                 >
                   <option value="">類別</option>
                   <option value="公立">公立</option>
                   <option value="私立">私立</option>
                 </select>
               )}
            </label>

            <label className="flex items-center gap-3 p-2 rounded hover:bg-white transition-colors cursor-pointer">
               <input 
                  type="radio" 
                  name="unitType"
                  value="醫療院所"
                  checked={basicInfo.unitType === '醫療院所'}
                  onChange={(e) => handleBasicInfoChange('unitType', e.target.value)}
                  className="w-4 h-4 text-primary-600 focus:ring-primary-500"
                />
               <span className="text-gray-700">醫療院所</span>
               {basicInfo.unitType === '醫療院所' && (
                 <select 
                   className="ml-2 p-1 text-sm border border-gray-300 rounded focus:ring-1 focus:ring-primary-500"
                   value={basicInfo.hospitalType}
                   onChange={(e) => handleBasicInfoChange('hospitalType', e.target.value)}
                   onClick={(e) => e.stopPropagation()}
                 >
                   <option value="">類別</option>
                   <option value="公立">公立</option>
                   <option value="私立">私立</option>
                 </select>
               )}
            </label>

            <label className="flex items-center gap-3 p-2 rounded hover:bg-white transition-colors cursor-pointer">
                <input 
                  type="radio" 
                  name="unitType"
                  value="其他"
                  checked={basicInfo.unitType === '其他'}
                  onChange={(e) => handleBasicInfoChange('unitType', e.target.value)}
                  className="w-4 h-4 text-primary-600 focus:ring-primary-500"
                />
                <span className="text-gray-700">其他</span>
                {basicInfo.unitType === '其他' && (
                  <input 
                    type="text" 
                    placeholder="請說明"
                    className="ml-2 p-1 border-b border-gray-400 outline-none w-32 bg-transparent focus:border-primary-500"
                    value={basicInfo.unitTypeOther}
                    onChange={(e) => handleBasicInfoChange('unitTypeOther', e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                  />
                )}
            </label>
          </div>
        </div>

        <div className="col-span-2 space-y-1">
          <label className="block text-sm font-semibold text-gray-700">5. 行業別</label>
          <select 
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none hover:bg-gray-50"
              value={basicInfo.industry}
              onChange={(e) => handleBasicInfoChange('industry', e.target.value)}
            >
              <option value="">請選擇行業別</option>
              {INDUSTRIES.map(ind => (
                <option key={ind} value={ind}>{ind}</option>
              ))}
            </select>
        </div>

        <div className="col-span-2 md:col-span-1 space-y-1">
          <label className="block text-sm font-semibold text-gray-700">6. 員工人數</label>
          <div className="flex gap-4 p-4 bg-gray-50 rounded-xl border border-gray-100">
             <div className="flex items-center gap-2 flex-1">
               <span className="text-gray-600 font-medium">男性:</span>
               <input 
                type="number" 
                min="0"
                className="w-full p-2 border border-gray-300 rounded focus:ring-2 focus:ring-primary-500 outline-none"
                value={basicInfo.employeesMale}
                onChange={(e) => handleBasicInfoChange('employeesMale', e.target.value)}
              />
             </div>
             <div className="flex items-center gap-2 flex-1">
               <span className="text-gray-600 font-medium">女性:</span>
               <input 
                type="number" 
                min="0"
                className="w-full p-2 border border-gray-300 rounded focus:ring-2 focus:ring-primary-500 outline-none"
                value={basicInfo.employeesFemale}
                onChange={(e) => handleBasicInfoChange('employeesFemale', e.target.value)}
              />
             </div>
          </div>
        </div>

        <div className="col-span-2 md:col-span-1 space-y-1">
          <label className="block text-sm font-semibold text-gray-700">7. 單位規模 (系統自動計算)</label>
          <div className="relative">
             <input 
                type="text" 
                readOnly
                className="w-full p-3 bg-gray-100 border border-gray-300 rounded-lg text-primary-700 font-bold"
                value={basicInfo.scale}
                placeholder="輸入人數後自動顯示"
            />
            {basicInfo.scale && <Check className="absolute right-3 top-3 text-primary-500 w-5 h-5" />}
          </div>
        </div>
        
        <div className="col-span-2 border-t pt-6 mt-2">
            <h3 className="text-lg font-bold text-gray-800 mb-6 flex items-center gap-2">
                <Users className="text-primary-600" size={20} /> 聯絡人資訊
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                 <div className="space-y-1">
                    <label className="block text-sm text-gray-600">8. 姓名</label>
                    <input type="text" className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none" value={basicInfo.contactName} onChange={e => handleBasicInfoChange('contactName', e.target.value)} />
                 </div>
                 <div className="space-y-1">
                    <label className="block text-sm text-gray-600">9. 部門</label>
                    <input type="text" className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none" value={basicInfo.contactDept} onChange={e => handleBasicInfoChange('contactDept', e.target.value)} />
                 </div>
                 <div className="space-y-1">
                    <label className="block text-sm text-gray-600">10. 職稱</label>
                    <input type="text" className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none" value={basicInfo.contactTitle} onChange={e => handleBasicInfoChange('contactTitle', e.target.value)} />
                 </div>
                 <div className="space-y-1">
                    <label className="block text-sm text-gray-600">11. 電話</label>
                    <input type="tel" className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none" value={basicInfo.contactPhone} onChange={e => handleBasicInfoChange('contactPhone', e.target.value)} />
                 </div>
                 <div className="col-span-2 space-y-1">
                    <label className="block text-sm text-gray-600">12. E-mail</label>
                    <input type="email" className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none" value={basicInfo.contactEmail} onChange={e => handleBasicInfoChange('contactEmail', e.target.value)} />
                 </div>
            </div>
        </div>
      </div>
       <div className="mt-8 flex justify-end">
        <button 
          onClick={() => setActiveTab(Tabs.QUESTIONNAIRE)}
          className="flex items-center gap-2 px-8 py-3 bg-primary-600 text-white rounded-xl shadow-lg hover:bg-primary-700 hover:shadow-xl hover:-translate-y-0.5 transition-all font-bold text-lg"
        >
          下一步：填寫問卷 <ChevronRight />
        </button>
      </div>
    </div>
  );

  const renderQuestionnaire = () => {
    // Group questions by Part
    const parts = [
      { id: 1, title: '一、職場健康政策與計畫 (30 分)' },
      { id: 2, title: '二、職場健康需求評估 (14 分)' },
      { id: 3, title: '三、健康促進設施與活動 (38 分)' },
      { id: 4, title: '四、生理健康工作環境 (12 分)' },
      { id: 5, title: '五、社區參與 (6 分)' },
    ];

    // Specialized description for Part 5 - Card Style
    const part5Description = (
      <div className="p-6 bg-amber-50 border-b border-amber-100 animate-fade-in">
        <div className="bg-white rounded-xl p-6 shadow-sm border border-amber-100 ring-1 ring-amber-100/50">
             <div className="flex items-start gap-3 mb-4">
                 <div className="p-2 bg-amber-100 rounded-full text-amber-600 shrink-0 mt-1">
                    <Info size={20} />
                 </div>
                 <div className="space-y-2">
                    <h4 className="font-bold text-amber-900 text-lg">擴大關懷：員工眷屬與社區</h4>
                    <p className="text-amber-800 leading-relaxed text-sm opacity-90">
                        企業應創造正向友善的工作環境，不只照顧員工，也應擴及其家庭成員及社區。
                        若能推動健康促進至眷屬、承攬商（如清潔員、保全），能減少因照顧生病家人而請假的問題，提升認同感。
                        請檢視您的單位活動是否已推廣（或考量）到這些群體？
                    </p>
                 </div>
             </div>
             
             <div className="pl-14">
                <p className="font-bold text-amber-800 text-sm mb-2">活動範例參考：</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm text-gray-600">
                    <div className="flex items-start gap-2"><div className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 shrink-0"></div>推廣多喝水、少喝含糖飲料</div>
                    <div className="flex items-start gap-2"><div className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 shrink-0"></div>號召眷屬/承攬商參加社區健康活動(四癌篩檢/疫苗)</div>
                    <div className="flex items-start gap-2"><div className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 shrink-0"></div>提供交通車供民眾搭乘，避免事故</div>
                    <div className="flex items-start gap-2"><div className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 shrink-0"></div>與社區規劃菸害防制策略</div>
                    <div className="flex items-start gap-2"><div className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 shrink-0"></div>提供托兒補貼或空間，降低家庭壓力</div>
                    <div className="flex items-start gap-2"><div className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 shrink-0"></div>認養公園綠地供健走伸展，增進社區團結</div>
                </div>
             </div>
        </div>
      </div>
    );

    return (
      <div className="max-w-4xl mx-auto space-y-8 animate-slide-up pb-24">
        {parts.map(part => (
          <div key={part.id} className="bg-white rounded-2xl shadow-lg border border-gray-100 overflow-hidden transition-shadow hover:shadow-xl">
            <div className="bg-gradient-to-r from-primary-50 to-white px-6 py-5 border-b border-primary-100 flex items-center justify-between">
              <h3 className="text-xl font-bold text-primary-900">{part.title}</h3>
              <div className="text-primary-400 bg-white p-1.5 rounded-full shadow-sm">
                 <CheckSquare size={20} />
              </div>
            </div>
            
            {/* Show special description for Part 5 */}
            {part.id === 5 && part5Description}

            <div className="divide-y divide-gray-100">
              {QUESTIONS.filter(q => q.partId === part.id).map(q => (
                <div key={q.id} id={`q-${q.id}`} className="p-6 md:p-8 hover:bg-gray-50/50 transition-colors duration-200">
                  <div className="flex flex-col md:flex-row gap-6">
                    <div className="flex-1">
                      <div className="flex gap-4">
                        <span className="font-bold text-gray-400 text-lg w-8 pt-0.5">{q.id}.</span>
                        <div className="flex-1">
                          <p className="text-gray-800 font-bold text-lg mb-3 leading-snug tracking-wide">{q.questionText}</p>
                          <span className="inline-block px-2 py-1 bg-gray-100 text-gray-500 text-xs rounded-md font-medium mb-3">配分: {q.points}</span>
                          {q.note && (
                            <div className="text-red-600 text-sm whitespace-pre-line bg-red-50 p-4 rounded-lg border border-red-100 mt-2 flex items-start gap-2">
                               <Info size={16} className="shrink-0 mt-0.5" />
                               <span>{q.note}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                    
                    {/* Interactive Yes/No Buttons */}
                    <div className="flex md:flex-col gap-3 md:w-40 shrink-0 pt-1">
                      <label 
                        className={`
                          flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl cursor-pointer transition-all duration-200 border
                          ${answers[q.id] === true 
                            ? 'bg-primary-600 border-primary-600 text-white shadow-md shadow-primary-200 scale-105' 
                            : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300'}
                        `}
                      >
                        <input 
                          type="radio" 
                          name={`q-${q.id}`} 
                          className="hidden" 
                          checked={answers[q.id] === true}
                          onChange={() => handleAnswerChange(q.id, true)}
                        />
                        <Check size={18} className={answers[q.id] === true ? 'text-white' : 'text-gray-400'} />
                        <span className="font-bold">是</span>
                      </label>

                      <label 
                         className={`
                          flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl cursor-pointer transition-all duration-200 border
                          ${answers[q.id] === false 
                            ? 'bg-gray-600 border-gray-600 text-white shadow-md shadow-gray-200 scale-105' 
                            : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300'}
                        `}
                      >
                        <input 
                          type="radio" 
                          name={`q-${q.id}`} 
                          className="hidden" 
                          checked={answers[q.id] === false}
                          onChange={() => handleAnswerChange(q.id, false)}
                        />
                         <X size={18} className={answers[q.id] === false ? 'text-white' : 'text-gray-400'} />
                        <span className="font-bold">否</span>
                      </label>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}

        <div className="fixed bottom-0 left-0 right-0 bg-white/90 backdrop-blur-md border-t border-gray-200 p-4 shadow-[0_-5px_20px_rgba(0,0,0,0.05)] z-20 flex justify-center gap-4">
            <button 
                onClick={() => setActiveTab(Tabs.BASIC_INFO)}
                className="px-6 py-3 bg-white text-gray-700 border border-gray-300 rounded-xl hover:bg-gray-50 font-medium transition-all"
            >
                上一步
            </button>
            <button 
                onClick={validateAndSubmit}
                className="px-10 py-3 bg-gradient-to-r from-primary-600 to-primary-700 text-white rounded-xl shadow-lg shadow-primary-200 hover:shadow-xl hover:-translate-y-1 transform transition-all font-bold text-lg flex items-center gap-2"
            >
                <CheckSquare className="w-5 h-5" /> 送出計算
            </button>
        </div>
      </div>
    );
  };

  const renderResult = () => {
    const { categoryResults, totalScore } = calculateResults();
    const evaluation = getEvaluation(totalScore);

    return (
      <div className="max-w-5xl mx-auto space-y-8 animate-slide-up pb-10">
        
        {/* Header Summary */}
        <div className="bg-gradient-to-br from-primary-600 via-primary-700 to-primary-800 rounded-3xl shadow-xl p-10 text-white relative overflow-hidden">
             {/* decorative circles */}
             <div className="absolute top-0 right-0 -mt-10 -mr-10 w-40 h-40 bg-white opacity-10 rounded-full blur-2xl"></div>
             <div className="absolute bottom-0 left-0 -mb-10 -ml-10 w-40 h-40 bg-white opacity-10 rounded-full blur-2xl"></div>

            <div className="flex flex-col md:flex-row justify-between items-center relative z-10">
                <div className="text-center md:text-left">
                    <h2 className="text-4xl font-extrabold mb-2 tracking-tight">{basicInfo.unitName || '貴單位'}</h2>
                    <p className="opacity-90 text-xl font-light">職場健康促進表現評估結果</p>
                </div>
                <div className="mt-8 md:mt-0 text-center bg-white/20 p-6 rounded-2xl backdrop-blur-md shadow-inner border border-white/30">
                    <span className="block text-sm opacity-90 uppercase tracking-widest font-semibold mb-1">總得分</span>
                    <div className="flex items-baseline justify-center">
                        <span className="text-6xl font-black tracking-tighter shadow-black drop-shadow-sm">{totalScore}</span>
                        <span className="text-2xl ml-2 font-medium opacity-80">/ 100</span>
                    </div>
                </div>
            </div>
        </div>

        {/* Charts & Basic Info Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* Radar Chart */}
            <div className="bg-white p-6 rounded-2xl shadow-lg border border-gray-100 flex flex-col items-center">
                <h3 className="text-xl font-bold text-gray-800 mb-6 flex items-center gap-2 w-full border-b pb-4">
                    <Activity className="text-primary-500" /> 五大構面表現
                </h3>
                <Chart data={categoryResults} />
            </div>

            {/* Breakdown Table */}
            <div className="bg-white p-6 rounded-2xl shadow-lg border border-gray-100">
                <h3 className="text-xl font-bold text-gray-800 mb-6 flex items-center gap-2 w-full border-b pb-4">
                    <ClipboardList className="text-primary-500" /> 得分明細
                </h3>
                <div className="overflow-hidden rounded-xl border border-gray-200">
                    <table className="w-full text-sm text-left text-gray-600">
                        <thead className="text-xs text-gray-700 uppercase bg-gray-50 border-b border-gray-200">
                            <tr>
                                <th className="px-4 py-4 font-bold">構面</th>
                                <th className="px-4 py-4 text-right font-bold">得分/配分</th>
                                <th className="px-4 py-4 text-right font-bold">得分率</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                            {categoryResults.map(cat => (
                                <tr key={cat.partId} className="hover:bg-gray-50/80 transition-colors">
                                    <td className="px-4 py-4 font-medium text-gray-900" title={cat.title}>
                                        {cat.title.replace(/^[一二三四五]、/, '')}
                                    </td>
                                    <td className="px-4 py-4 text-right">
                                        <span className="font-bold text-primary-700 text-lg">{cat.score}</span> 
                                        <span className="text-gray-400 mx-1">/</span>
                                        {cat.totalPoints}
                                    </td>
                                    <td className="px-4 py-4 text-right">
                                        <div className="flex flex-col items-end gap-1">
                                            <span className="font-bold text-gray-800">{cat.percentage.toFixed(0)}%</span>
                                            <div className="w-24 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                                                <div 
                                                    className="bg-primary-500 h-1.5 rounded-full transition-all duration-1000 ease-out" 
                                                    style={{width: `${cat.percentage}%`}}
                                                ></div>
                                            </div>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        {/* Evaluation Section */}
        <div className="bg-white p-10 rounded-2xl shadow-lg border border-gray-100 border-l-[6px] border-l-primary-500 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-32 h-32 bg-primary-50 rounded-bl-full -mr-8 -mt-8 opacity-50 pointer-events-none"></div>
            <h3 className="text-2xl font-bold text-primary-800 mb-6 relative z-10">{evaluation.title}</h3>
            <div className="prose max-w-none text-gray-700 whitespace-pre-line leading-relaxed relative z-10">
                {evaluation.content}
            </div>
        </div>

        {/* Detailed Suggestions Section with Icons */}
        <div className="space-y-6">
            <h3 className="text-2xl font-bold text-gray-800 flex items-center gap-3 px-2">
                <div className="p-2 bg-primary-100 rounded-lg text-primary-600">
                    <ShieldCheck size={24} />
                </div>
                各項議題詳細建議
            </h3>
            
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {SUGGESTIONS_DATA.map((item, index) => {
                const IconComponent = ICON_MAP[item.icon] || FileText;
                return (
                  <div key={index} className="bg-white rounded-2xl shadow-sm border border-gray-100 hover:shadow-xl hover:-translate-y-1 transition-all duration-300 overflow-hidden group">
                    <div className="bg-gray-50/80 px-6 py-5 border-b border-gray-100 flex items-center gap-4 group-hover:bg-primary-50/50 transition-colors">
                      <div className="p-3 bg-white rounded-xl shadow-sm text-primary-600 border border-gray-100 group-hover:scale-110 transition-transform">
                        <IconComponent size={22} />
                      </div>
                      <h4 className="font-bold text-gray-800 text-lg group-hover:text-primary-800 transition-colors">{item.title}</h4>
                    </div>
                    <div className="p-7">
                      <div className="text-gray-600 whitespace-pre-line leading-relaxed text-sm">
                        {item.content}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
        </div>

        <div className="flex justify-center pt-12">
            <button 
                onClick={() => window.print()}
                className="px-8 py-4 bg-gray-800 text-white rounded-xl shadow-lg hover:bg-gray-900 hover:shadow-2xl transition-all font-bold flex items-center gap-3"
            >
                <FileText size={20} />
                列印 / 存為 PDF
            </button>
        </div>

      </div>
    );
  };

  return (
    <div className="min-h-screen bg-gray-50 font-sans selection:bg-primary-100 selection:text-primary-800">
      <AlertDialog 
        isOpen={alertState.isOpen} 
        title={alertState.title} 
        message={alertState.message} 
        onClose={() => setAlertState(prev => ({ ...prev, isOpen: false }))} 
      />

      {/* Header */}
      <header className="bg-white/80 backdrop-blur-md shadow-sm sticky top-0 z-30 transition-all border-b border-gray-100">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-20">
            <div className="flex items-center gap-3">
              <div className="bg-primary-600 p-2 rounded-lg text-white shadow-lg shadow-primary-200">
                  <Activity className="h-6 w-6" />
              </div>
              <h1 className="text-xl font-bold text-gray-800 hidden sm:block tracking-tight">職場健康促進表現計分表</h1>
              <h1 className="text-xl font-bold text-gray-800 sm:hidden">健康促進計分</h1>
            </div>
            
            {/* Tabs */}
            <nav className="flex p-1 bg-gray-100/50 rounded-xl">
              {[
                { id: Tabs.INTRO, label: '說明', icon: FileText },
                { id: Tabs.BASIC_INFO, label: '基本資料', icon: ClipboardList },
                { id: Tabs.QUESTIONNAIRE, label: '問卷', icon: CheckSquare },
                { id: Tabs.RESULT, label: '結果', icon: Activity },
              ].map(tab => {
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`
                      px-4 py-2 rounded-lg text-sm font-bold transition-all flex items-center gap-2
                      ${isActive 
                        ? 'bg-white text-primary-600 shadow-sm scale-100' 
                        : 'text-gray-500 hover:text-gray-700 hover:bg-gray-200/50 scale-95'}
                    `}
                  >
                    <tab.icon className="w-4 h-4" />
                    <span className="hidden sm:inline">{tab.label}</span>
                  </button>
                )
              })}
            </nav>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        {activeTab === Tabs.INTRO && renderIntro()}
        {activeTab === Tabs.BASIC_INFO && renderBasicInfo()}
        {activeTab === Tabs.QUESTIONNAIRE && renderQuestionnaire()}
        {activeTab === Tabs.RESULT && renderResult()}
      </main>

    </div>
  );
};

export default App;