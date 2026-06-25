// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract ExamRegistry {
    address public owner;

    struct Exam {
        string examType;      // "NEET" or "JEE"
        uint256 startTime;    // Unix timestamp
        uint256 duration;     // seconds
        string mcqFileHash;   // IPFS or SHA256 hash of uploaded CSV
        bool isActive;
    }

    struct Student {
        string name;
        string email;
        string rollNumber;
        string examType;
        bytes32 paperHash;    // unique per-student question hash
        bool isRegistered;
        bool hasAccessed;
    }

    mapping(string => Exam) public exams;
    mapping(bytes32 => Student) public students;
    mapping(string => bytes32[]) public examStudents;

    event ExamCreated(string examType, uint256 startTime, uint256 duration);
    event StudentRegistered(string rollNumber, string examType, bytes32 paperHash);
    event PaperAccessed(bytes32 paperHash, uint256 timestamp);
    event MCQUploaded(string examType, string fileHash);

    modifier onlyOwner() {
        require(msg.sender == owner, "Only university can call this");
        _;
    }

    modifier examExists(string memory examType) {
        require(exams[examType].isActive, "Exam not found or inactive");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    function createExam(
        string memory examType,
        uint256 startTime,
        uint256 duration,
        string memory mcqFileHash
    ) public onlyOwner {
        exams[examType] = Exam({
            examType: examType,
            startTime: startTime,
            duration: duration,
            mcqFileHash: mcqFileHash,
            isActive: true
        });
        emit ExamCreated(examType, startTime, duration);
        emit MCQUploaded(examType, mcqFileHash);
    }

    function registerStudent(
        string memory name,
        string memory email,
        string memory rollNumber,
        string memory examType,
        bytes32 paperHash
    ) public examExists(examType) {
        require(!students[paperHash].isRegistered, "Hash already used");

        students[paperHash] = Student({
            name: name,
            email: email,
            rollNumber: rollNumber,
            examType: examType,
            paperHash: paperHash,
            isRegistered: true,
            hasAccessed: false
        });

        examStudents[examType].push(paperHash);
        emit StudentRegistered(rollNumber, examType, paperHash);
    }

    function verifyAndAccess(bytes32 paperHash) public examExists(students[paperHash].examType) returns (bool) {
        require(students[paperHash].isRegistered, "Invalid hash");
        
        string memory examType = students[paperHash].examType;
        Exam memory exam = exams[examType];
        
        require(block.timestamp >= exam.startTime, "Exam not started yet");
        require(block.timestamp <= exam.startTime + exam.duration, "Exam window closed");

        students[paperHash].hasAccessed = true;
        emit PaperAccessed(paperHash, block.timestamp);
        return true;
    }

    function isValidHash(bytes32 paperHash) public view returns (bool) {
        return students[paperHash].isRegistered;
    }

    function getExam(string memory examType) public view returns (
        uint256 startTime,
        uint256 duration,
        string memory mcqFileHash,
        bool isActive
    ) {
        Exam memory e = exams[examType];
        return (e.startTime, e.duration, e.mcqFileHash, e.isActive);
    }

    function getStudent(bytes32 paperHash) public view returns (
        string memory name,
        string memory rollNumber,
        string memory examType,
        bool hasAccessed
    ) {
        Student memory s = students[paperHash];
        return (s.name, s.rollNumber, s.examType, s.hasAccessed);
    }

    function getExamStudentCount(string memory examType) public view returns (uint256) {
        return examStudents[examType].length;
    }
}
