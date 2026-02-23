import { useMemo, useState, useEffect, useRef } from 'react'
import './App.css'

// 백엔드 RAG API 엔드포인트, 캘린더 엔드포인트
const RAG_API_URL = 'http://127.0.0.1:8100/rag/query'
const CAL_API_URL = 'http://localhost:8100/calendar/events'
const BACKEND_BASE_URL = new URL(RAG_API_URL).origin

function App() {
  // const [pageImages, setPageImages] = useState([]);
  const [imageFile, setImageFile] = useState(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState(null);
  const fileInputRef = useRef(null);
  // 채팅 창 스크롤 관리를 위한 Ref
  const chatWindowRef = useRef(null);
  
  const formatISODate = (date) => {
    const year = date.getFullYear()
    const month = `${date.getMonth() + 1}`.padStart(2, '0')
    const day = `${date.getDate()}`.padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  const today = useMemo(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), now.getDate())
  }, [])

  const initialMessages = useMemo(() => [], [])

  const [messages, setMessages] = useState(initialMessages)
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [calendarConnected, setCalendarConnected] = useState(false)

  const calendar = useMemo(() => {
    const year = today.getFullYear()
    const monthIndex = today.getMonth()

    const firstDay = new Date(year, monthIndex, 1)
    const startWeekday = firstDay.getDay()
    const daysInMonth = new Date(year, monthIndex + 1, 0).getDate()

    const cells = []
    for (let i = 0; i < startWeekday; i += 1) {
      cells.push(null)
    }

    for (let day = 1; day <= daysInMonth; day += 1) {
      const currentDate = new Date(year, monthIndex, day)
      cells.push({
        key: formatISODate(currentDate),
        label: day,
        isToday: day === today.getDate()
      })
    }

    while (cells.length % 7 !== 0) {
      cells.push(null)
    }

    return {
      label: `${year}년 ${monthIndex + 1}월`,
      cells
    }
  }, [today])

  const [calendarEvents, setCalendarEvents] = useState([])

  // 캘린더 이벤트 조회 함수
  const fetchEvents = async () => {
    try {
      const resp = await fetch(`${CAL_API_URL}?limit=10`)
      if (!resp.ok) {
        throw new Error(`Calendar API error: ${resp.status}`)
      }
      const data = await resp.json()
      setCalendarEvents(data.events || [])
    } catch (err) {
      console.error('캘린더 이벤트 조회 실패:', err)
      setCalendarEvents([])
    }
  }

  // 마운트 시 한 번 호출
  useEffect(() => {
    fetchEvents()
  }, [])

  // URL 쿼리에서 캘린더 동기화 여부 감지
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('calendar') === 'connected') {
      setCalendarConnected(true)
      // 쿼리 파라미터 제거 (새로고침해도 깔끔하게 유지)
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  // 자동 스크롤 효과
  useEffect(() => {
    if (chatWindowRef.current) {
      chatWindowRef.current.scrollTop = chatWindowRef.current.scrollHeight;
    }
  }, [messages, loading]); 

  // 파일 첨부 핸들러
  const handleFileChange = (e) => {
    const file = e.target.files?.[0] || null;
    setImageFile(file);
    if (file) {
      // FileReader를 사용하여 미리보기 URL 생성
      const reader = new FileReader();
      reader.onloadend = () => {
        setImagePreviewUrl(reader.result);
      };
      reader.readAsDataURL(file);
    } else {
      setImagePreviewUrl(null);
    }
  };
  
  // 첨부 이미지 제거 핸들러
  const handleRemoveImage = () => {
    setImageFile(null);
    setImagePreviewUrl(null);
    if (fileInputRef.current) {
        fileInputRef.current.value = ''; // input file 값 초기화
    }
  };

  // 엔터 키 입력 핸들러
  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault(); // 기본 Enter 동작(줄 바꿈) 방지
        handleSubmit(event); // 폼 제출
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    const trimmed = question.trim()
    // 텍스트도 이미지도 없으면 리턴
    if ((!trimmed && !imageFile) || loading) return

    //  userMessage에 imagePreviewUrl (전송 이미지) 추가
    const userMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      name: '나',
      content: trimmed || (imageFile ? `(이미지 전송: ${imageFile.name})` : '(이미지 전송)'),
      imageUrl: imageFile ? imagePreviewUrl : null, // 전송할 이미지 URL 저장
    }

    setMessages((prev) => [...prev, userMessage])
    setQuestion('')
    setLoading(true)
    setImagePreviewUrl(null);

    try {
      // FormData로 텍스트 + 이미지 + k 값 전송 (필드명 "file"로 맞춤)
      const formData = new FormData()
      formData.append('query', trimmed)
      formData.append('k', '5') // 기본 k 값, 필요시 상태로 관리 가능
      if (imageFile) {
        // 백엔드 /ask는 "file" 필드명으로 업로드 파일을 받도록 구현되어 있음
        formData.append('file', imageFile)
      }

      const resp = await fetch(RAG_API_URL, {
        method: 'POST',
        body: formData
      })

      if (!resp.ok) {
        throw new Error(`RAG API error: ${resp.status}`)
      }

      const data = await resp.json()
      const answerText = data.answer ?? data.result ?? '응답을 가져오지 못했어요.'
      const intent = data.intent ?? 'rag'
      const isReminder = intent === 'reminder'

      // 백엔드에서 내려주는 pages 배열 사용 (PageInfo 리스트)
      const pages = Array.isArray(data.pages) ? data.pages : []

      let decoratedAnswer = answerText
      let sourceImage = null

      if (!isReminder && pages.length > 0) {
        const firstPage = pages[0]
        const pageNum = firstPage.page ?? firstPage.page_number

        // 백엔드에서 내려주는 필드 우선순위:
        // 1) image_base64 (data URL)
        // 2) image_url    (/manual_images/..., 절대/상대 URL)
        // 3) image_path   (로컬 경로)
        const pageImageBase64 = firstPage.image_base64 ?? null
        const pageImageUrl = firstPage.image_url ?? firstPage.page_image ?? firstPage.pageImage ?? null
        const pageImagePath = firstPage.image_path ?? null

        // 이미 답변에 참고 문구가 없다면 한 줄 추가
        if (pageNum && !answerText.includes('참고:')) {
          decoratedAnswer += `\n\n(참고: 매뉴얼 p.${pageNum} 기반 답변)`
        }

        // 우선순위에 따라 sourceImage 결정
        if (pageImageBase64) {
          // data:image/...;base64,... 형태 그대로 사용
          sourceImage = pageImageBase64
        } else if (pageImageUrl) {
          sourceImage = pageImageUrl
        } else if (pageImagePath) {
          sourceImage = pageImagePath
        }
      }

      const agentMessage = {
        id: `agent-${Date.now()}`,
        role: 'agent',
        name: 'Mindual',
        content: decoratedAnswer,
        variant: isReminder ? 'reminder' : undefined,
        sourceImage
      }

      setMessages((prev) => [...prev, agentMessage])

      // 리마인더인 경우, 캘린더 재조회
      if (isReminder) {
        await fetchEvents()
      }
    } catch (error) {
      console.error(error)
      const agentMessage = {
        id: `agent-${Date.now()}`,
        role: 'agent',
        name: 'Mindual',
        content:
          '죄송해요, RAG 서버에 연결하는 데 문제가 발생했습니다.\n서버 상태를 확인한 후 다시 시도해 주세요.'
      }
      setMessages((prev) => [...prev, agentMessage])
    } finally {
      setLoading(false)
      setImageFile(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  }

  return (
    <div className="app">
      <div className="brand-bar">
        <div className="brand-title">MINDUAL</div>
        <div className="header-actions">
          <button type="button" className="primary ghost">
            메뉴얼
          </button>
          <button type="button" className="primary">사용자 설정</button>
        </div>
      </div>
      <main className="layout">
        <section className="panel chat-panel">
          <header>
            <div className="chat-title">
              <h1>질문하기</h1>
              <p className="subtitle">
                RAG 기반 에이전트 MINDUAL에게 궁금한 것을 전달하고 사용법에 대한 답변을 한눈에
                확인하세요.
              </p>
            </div>
            <span className="tag">{loading ? 'Thinking...' : 'Live'}</span>
          </header>

          {/* ✨ ref={chatWindowRef} 추가 */}
          <div className="chat-window" ref={chatWindowRef}>
            {messages.map((message) => (
              <div
                key={message.id}
                className={`chat-row ${message.role} ${message.variant ?? ''}`}
              >
                <div className="avatar">
                  {message.role === 'agent' ? '🤖' : '🙂'}
                </div>
                <div className="bubble">
                  <div className="bubble-header">
                    <span className="name">{message.name}</span>
                    {message.role === 'agent' && message.variant !== 'reminder' && (
                      <span className="source">지식 베이스 · 최신 매뉴얼</span>
                    )}
                  </div>
                  
                  {/* ✨ 수정: 사용자 메시지에 imageUrl이 있을 경우 이미지를 표시 */}
                  {message.role === 'user' && message.imageUrl ? (
                    <div className="user-image-wrapper">
                      <p>{message.content}</p>
                      <img
                        src={message.imageUrl}
                        alt="사용자 첨부 이미지"
                        className="user-sent-image" // ✨ 클래스 추가 (크기 조정용)
                      />
                    </div>
                  ) : (
                    <p>
                      {message.content.split('\n').map((line, index) => (
                        <span key={index}>
                          {line}
                          <br />
                        </span>
                      ))}
                    </p>
                  )}


                  {message.role === 'agent' && message.sourceImage && (
                    <div className="source-image-wrapper">
                      <p className="source-image-label">참고 페이지 이미지</p>
                      <img
                        src={
                          message.sourceImage.startsWith('data:') ||
                          message.sourceImage.startsWith('http')
                            ? message.sourceImage
                            : `${BACKEND_BASE_URL}${
                                message.sourceImage.startsWith('/') ? '' : '/'
                              }${message.sourceImage}`
                        }
                        alt="매뉴얼 페이지"
                        className="page-image"
                      />
                    </div>
                  )}
                </div>
              </div>
            ))}

            {/* 로딩 상태일 때 말풍선 표시 */}
            {loading && (
              <div key="loading-agent" className="chat-row agent thinking">
                <div className="avatar">🤖</div>
                <div className="bubble">
                  <div className="bubble-header">
                    <span className="name">Mindual</span>
                    <span className="source">지식 베이스 · 최신 매뉴얼</span>
                  </div>
                  <p>답변을 생성 중입니다...</p>
                </div>
              </div>
            )}

            {messages.length === 0 && !loading && (
              <div className="chat-empty-hint">
                아직 대화가 없어요. 아래 입력창에 질문을 남기면 매뉴얼 기반으로 답변해 드릴게요.
              </div>
            )}
          </div>

          <form className="input-area" onSubmit={handleSubmit}>
            <label htmlFor="question" className="sr-only">
              사용자 질문
            </label>
            <textarea
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              // 엔터 키 핸들러
              onKeyDown={handleKeyDown} 
              placeholder="질문을 입력하세요. ( Shift + Enter로 줄 바꿈 )"
              disabled={loading}
            />
            
            {imagePreviewUrl && (
              <div className="image-preview-wrapper small-preview"> {/* ✨ 클래스 추가 (크기 조정용) */}
                <p className="image-preview-label">첨부 이미지 미리보기</p>
                <img
                  src={imagePreviewUrl}
                  alt="첨부 이미지 미리보기"
                  className="image-preview"
                />
                <button 
                    type="button" 
                    className="remove-image-btn" 
                    onClick={handleRemoveImage}
                >
                    ❌
                </button>
              </div>
            )}

            <div className="form-actions">
              {/* 숨겨진 파일 input */}
              <input
                type="file"
                accept="image/*"
                ref={fileInputRef}
                style={{ display: 'none' }}
                onChange={handleFileChange}
              />

              <button
                type="button"
                className="secondary"
                onClick={() => fileInputRef.current?.click()}
                disabled={loading || !!imageFile}
              >
                📷 사진 첨부
              </button>

              <button 
                  type="submit" 
                  className="primary" 
                  // ✨ 수정: 텍스트 또는 이미지가 있을 때 전송 버튼 활성화 (이미지 첨부 여부만으로 비활성화하지 않음)
                  disabled={loading || (!question.trim() && !imageFile)} 
              >
                {loading ? '응답 생성 중...' : '전송'}
              </button>
            </div>
          </form>
        </section>

        {/* 오른쪽 패널은 그대로 유지 */}
        <aside className="panel assistant-panel">
          <div className="info-card">
            <h3>연결된 문서</h3>
            <ul>
              <li>
                LG_Purifier 공기청정기 사용설명서
                <span className="pill success">동기화</span>
              </li>
              <li>
                LG 에어컨 청소 가이드
                <span className="pill warning">업데이트 필요</span>
              </li>
              <li>
                서비스 FAQ.xlsx
                <span className="pill info">RAG 캐시</span>
              </li>
            </ul>
          </div>

          <div className="info-card calendar-card">
            <div className="calendar-header">
              <div>
                <h3>캘린더</h3>
                <p className="calendar-subtitle">
                  Google Calendar API와 연동하여 최신 배포 일정을 자동으로 받아옵니다.
                </p>
              </div>
              <button
                type="button"
                className={`primary ghost ${calendarConnected ? 'connected' : ''}`}
                onClick={() => {
                  if (!calendarConnected) {
                    // OAuth 인증 시작: 백엔드 캘린더 OAuth 엔드포인트로 이동
                    window.location.href = "http://localhost:8100/calendar/auth"
                  }
                }}
              >
                {calendarConnected ? '✅ Google Calendar 연결됨' : 'Google Calendar 연결됨'}
              </button>
            </div>
            <div className="calendar-meta">
              <span className="month-label">{calendar.label}</span>
              <span className="timezone">기준: Asia/Seoul</span>
            </div>

            <div className="weekday-grid">
              {['일', '월', '화', '수', '목', '금', '토'].map((weekday) => (
                <span key={weekday} className="weekday">
                  {weekday}
                </span>
              ))}
            </div>
            <div className="calendar-grid">
              {calendar.cells.map((cell, index) => {
                if (!cell) {
                  return <div key={`empty-${index}`} className="calendar-cell empty" />
                }

                const dailyEvents = calendarEvents.filter(
                  (event) => event.date === cell.key
                )

                return (
                  <div
                    key={cell.key}
                    className={`calendar-cell ${cell.isToday ? 'today' : ''} ${
                      dailyEvents.length ? 'has-event' : ''
                    }`}
                  >
                    <span className="day-number">{cell.label}</span>
                    {dailyEvents.length > 0 && <span className="event-dot" />}
                  </div>
                )
              })}
            </div>

            <div className="event-list">
              <h4>다가오는 일정</h4>
              <ul>
                {calendarEvents.map((event) => (
                  <li key={event.id}>
                    <div className="event-date">
                      {event.date.slice(5)} <span>{event.time}</span>
                    </div>
                    <div className="event-detail">
                      <p className="event-title">{event.title}</p>
                      <p className="event-location">{event.location}</p>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="api-note">
                연결 후에는 Google Calendar에서 승인한 이벤트만 표시되며, 오늘 날짜는
                보라색으로 강조됩니다.
              </p>
            </div>
          </div>
        </aside>
      </main>
    </div>
  )
}

export default App