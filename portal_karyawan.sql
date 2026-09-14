-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Aug 26, 2026 at 05:09 AM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.2.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `portal_karyawan`
--

-- --------------------------------------------------------

--
-- Table structure for table `announcement`
--

CREATE TABLE `announcement` (
  `id` int(11) NOT NULL,
  `title` varchar(255) NOT NULL,
  `content` text NOT NULL,
  `category` varchar(100) NOT NULL,
  `date` varchar(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `announcement`
--

INSERT INTO `announcement` (`id`, `title`, `content`, `category`, `date`) VALUES
(1, 'test', 'test', 'teal', '19 Aug 2026'),
(3, 'apa itu ', 'usahosdhhqsq', 'indigo', '19 Aug 2026');

-- --------------------------------------------------------

--
-- Table structure for table `jadwal_rapat`
--

CREATE TABLE `jadwal_rapat` (
  `id` int(11) NOT NULL,
  `judul` varchar(255) NOT NULL,
  `tanggal` date NOT NULL,
  `waktu` time NOT NULL,
  `peserta` text NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `jadwal_rapat`
--

INSERT INTO `jadwal_rapat` (`id`, `judul`, `tanggal`, `waktu`, `peserta`) VALUES
(1, 'Rapat ', '2026-08-20', '17:57:00', 'tim'),
(2, 'Rapat 33', '2026-08-20', '18:06:00', 'tim\r\n');

-- --------------------------------------------------------

--
-- Table structure for table `user`
--

CREATE TABLE `user` (
  `id` int(11) NOT NULL,
  `fullname` varchar(100) NOT NULL,
  `email` varchar(120) NOT NULL,
  `password_hash` varchar(256) NOT NULL,
  `role` varchar(20) NOT NULL,
  `superior_id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `user`
--

INSERT INTO `user` (`id`, `fullname`, `email`, `password_hash`, `role`, `superior_id`) VALUES
(1, 'rizky', 'ramadanrizky941@gmail.com', 'scrypt:32768:8:1$138lqEmLJ1HlJzEc$efcca4bf640434dca30b844c793944d641cfc9e92433005303657b4714d9bea01881e1241fddc5df7196114b2cf206c8bcbfea026990f69f05adf6674fd614ad', 'admin', NULL),
(2, 'budi', 'budi190@gmail.com', 'scrypt:32768:8:1$rifi3qgAcMfjUJXM$edf7f60284ba8a6973445c759d563dded71d421c57fc7d8f1e9229ac06cd4e45cc792e082301500cdce75a09eca97131088b8e6643cf3063486190fe8069e628', 'user', NULL),
(3, 'Komandan', 'atasan@gmail.com', 'scrypt:32768:8:1$nqJiNOuuPYLNpwWS$e571931b95170c0d0fa31c8e56079d988c96f2259866746ac071d8c36639b4456a8dda4ab9638136d9640e17aaaf3fb31fb0b2a826b18f7023f7bfaa7e10bd77', 'atasan', NULL);

--
-- Indexes for dumped tables
--

--
-- Indexes for table `announcement`
--
ALTER TABLE `announcement`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `jadwal_rapat`
--
ALTER TABLE `jadwal_rapat`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `user`
--
ALTER TABLE `user`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `email` (`email`),
  ADD KEY `superior_id` (`superior_id`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `announcement`
--
ALTER TABLE `announcement`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT for table `jadwal_rapat`
--
ALTER TABLE `jadwal_rapat`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3;

--
-- AUTO_INCREMENT for table `user`
--
ALTER TABLE `user`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- Constraints for dumped tables
--

--
-- Constraints for table `user`
--
ALTER TABLE `user`
  ADD CONSTRAINT `user_ibfk_1` FOREIGN KEY (`superior_id`) REFERENCES `user` (`id`);
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
